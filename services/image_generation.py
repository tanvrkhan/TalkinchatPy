"""Cloudflare Workers AI image generation with strict local validation."""

import base64
import binascii
import fcntl
import json
import os
import random
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from io import BytesIO
from urllib.parse import urlparse
from dataclasses import asdict, dataclass, replace
from collections.abc import Mapping

from PIL import Image, UnidentifiedImageError

import config
from services.cloudflare_diagnostics import new_request_id, sanitize, sanitize_text

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_BYTES = 5 * 1024 * 1024
MAX_RESPONSE_BYTES = ((MAX_IMAGE_BYTES + 2) // 3 * 4) + 64 * 1024
MAX_ERROR_BYTES = 64 * 1024
TEXT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
REFERENCE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"


@dataclass(frozen=True)
class ProviderDiagnostic:
    status: int | None = None
    code: str = ""
    category: str = "upstream error"
    request_id: str = ""
    provider_message: str = ""
    content_type: str = ""
    content_encoding: str = ""
    response_size: int | None = None
    ray_id: str = ""
    excerpt: str = ""


class ImageGenerationError(Exception):
    def __init__(self, message, diagnostic=None, *, request_id="",
                 provider_code="", provider_message=""):
        super().__init__(message)
        detail = diagnostic or ProviderDiagnostic()
        updates = {}
        if request_id and not detail.request_id:
            updates["request_id"] = request_id
        if provider_code and not detail.code:
            updates["code"] = str(provider_code)[:64]
        if provider_message and not detail.provider_message:
            updates["provider_message"] = sanitize_text(provider_message, 512)
        self.diagnostic = replace(detail, **updates) if updates else detail
        self.request_id = self.diagnostic.request_id
        self.provider_code = self.diagnostic.code
        self.provider_message = self.diagnostic.provider_message


class ImageAuthError(ImageGenerationError):
    pass


class ImageQuotaError(ImageGenerationError):
    pass


class ImageRejectedError(ImageGenerationError):
    pass


class ImageTimeoutError(ImageGenerationError):
    pass


class ImageResponseError(ImageGenerationError):
    pass


class ImageReferenceError(ImageResponseError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    path: str
    size: tuple[int, int]
    request_id: str = ""
    diagnostic: ProviderDiagnostic | None = None


@dataclass(frozen=True)
class GenerationMetadata:
    """Explicit caller context; credentials and HTTP headers cannot be supplied."""

    requester_id: str = ""
    requester_name: str = ""
    room_id: str = ""
    room_name: str = ""
    original_prompt: str = ""
    refined_prompt: str = ""


@dataclass(frozen=True)
class _APIResponse:
    payload: bytes | dict
    diagnostic: ProviderDiagnostic


@dataclass(frozen=True)
class _ReferenceImage:
    data: bytes
    domain: str
    size: tuple[int, int]


class _ImageLock:
    def __init__(self):
        self._thread_lock = threading.Lock()
        self._file = None

    def acquire(self, timeout):
        deadline = time.monotonic() + timeout
        if not self._thread_lock.acquire(timeout=timeout):
            return False
        try:
            self._file = open(config.IMAGE_LOCK_FILE, "a+", encoding="utf-8")
            while True:
                try:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        self.release()
                        return False
                    time.sleep(0.05)
        except Exception:
            self.release()
            raise

    def release(self):
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None
        if self._thread_lock.locked():
            self._thread_lock.release()


_generation_lock = _ImageLock()


def _provider_details(payload):
    if not isinstance(payload, dict):
        return "", ""
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        error = errors[0]
        return (sanitize_text(str(error.get("code") or ""), 64),
                sanitize_text(error.get("message"), 512))
    error = payload.get("error")
    if isinstance(error, dict):
        return (sanitize_text(str(error.get("code") or payload.get("code") or ""), 64),
                sanitize_text(error.get("message"), 512))
    message = payload.get("message")
    if not isinstance(message, str) and isinstance(error, str):
        message = error
    return (sanitize_text(str(payload.get("code") or ""), 64),
            sanitize_text(message, 512))


def _provider_code(payload):
    return _provider_details(payload)[0]


def _with_provider(diagnostic, payload):
    code, message = _provider_details(payload)
    return replace(
        diagnostic,
        code=code or diagnostic.code,
        provider_message=message or diagnostic.provider_message,
    )


def _classify_api_error(payload, reference=False, status=None, diagnostic=None):
    text = json.dumps(payload).lower()
    detail = _with_provider(
        diagnostic or ProviderDiagnostic(status=status), payload,
    )
    if status is not None and detail.status is None:
        detail = replace(detail, status=status)
    if (status == 429 or detail.code in {"3036", "3040"}
            or "quota" in text or "limit" in text or "neuron" in text):
        raise ImageQuotaError(
            "Cloudflare image quota is exhausted",
            replace(detail, category="quota exhausted"),
        )
    if "safety" in text or "content" in text or "moderation" in text:
        raise ImageRejectedError(
            "Image request was rejected",
            replace(detail, category="content rejected"),
        )
    if reference:
        raise ImageReferenceError(
            "Cloudflare rejected the reference image",
            replace(detail, category="reference rejected"),
        )
    raise ImageResponseError(
        "Cloudflare returned an unsuccessful response",
        replace(detail, category="invalid request" if status == 400 else "upstream error"),
    )


def safe_diagnostic(error):
    diagnostic = getattr(error, "diagnostic", None)
    if diagnostic is None:
        return ""
    parts = []
    if diagnostic.request_id:
        parts.append(f"request {diagnostic.request_id}")
    if diagnostic.status is not None:
        parts.append(f"HTTP {diagnostic.status}")
    if diagnostic.code:
        parts.append(diagnostic.code)
    if diagnostic.category:
        parts.append(diagnostic.category)
    return " / ".join(parts)


def is_reference_url(url):
    parsed = urlparse(url) if isinstance(url, str) else None
    return bool(parsed and parsed.scheme == "https" and parsed.hostname == "cdn.talkinchat.com")


def _response_error(message, diagnostic, category=None):
    detail = replace(diagnostic, category=category) if category else diagnostic
    return ImageResponseError(message, detail)


def _decode_generated_image(data, reference=False, diagnostic=None):
    detail = diagnostic or ProviderDiagnostic()
    if not isinstance(data, dict):
        _classify_api_error(data, reference, diagnostic=detail)
    result = data.get("result")
    encoded = None
    if isinstance(result, dict):
        encoded = result.get("image")
    elif isinstance(result, str):
        encoded = result
    if encoded is None:
        encoded = data.get("image")
    if data.get("success") is False or (encoded is None and data.get("errors")):
        _classify_api_error(data, reference, status=detail.status, diagnostic=detail)
    if not isinstance(encoded, str):
        raise _response_error(
            "Cloudflare response did not contain an image", detail, "missing image",
        )
    if encoded.startswith("data:image/"):
        marker = ";base64,"
        marker_at = encoded.find(marker)
        if marker_at < 0:
            raise _response_error(
                "Cloudflare returned invalid image data", detail, "invalid image data",
            )
        encoded = encoded[marker_at + len(marker):]
    max_encoded = ((MAX_IMAGE_BYTES + 2) // 3 * 4) + 4
    if len(encoded) > max_encoded:
        raise _response_error(
            "Cloudflare image exceeded the size limit", detail, "response too large",
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise _response_error(
            "Cloudflare returned invalid image data", detail, "invalid image data",
        ) from None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise _response_error(
            "Cloudflare image exceeded the size limit", detail, "response too large",
        )
    return raw


def _save_generated_image(raw, diagnostic=None):
    detail = diagnostic or ProviderDiagnostic()
    suffix = ".png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
    if suffix == ".jpg" and not raw.startswith(b"\xff\xd8\xff"):
        raise _response_error(
            "Cloudflare returned non-image data", detail, "invalid image data",
        )
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="howdies-imagine-", suffix=suffix,
                                         delete=False) as output:
            output.write(raw)
            path = output.name
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            size = image.size
        return GeneratedImage(path, size, detail.request_id, detail)
    except (UnidentifiedImageError, OSError, ValueError):
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        raise _response_error(
            "Cloudflare returned an invalid image", detail, "invalid image data",
        ) from None


def _header(response, name):
    try:
        headers = response.headers
    except (AttributeError, TypeError):
        return ""
    try:
        value = headers.get(name, "")
    except (AttributeError, TypeError):
        value = ""
    if value:
        return str(value).strip()
    try:
        for key, candidate in headers.items():
            if str(key).lower() == name.lower():
                return str(candidate).strip()
    except (AttributeError, TypeError):
        pass
    return ""


def _response_content_type(response):
    return _header(response, "Content-Type").split(";", 1)[0].lower()


def _response_content_encoding(response):
    return _header(response, "Content-Encoding").lower()


def _response_status(response):
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    try:
        value = response.getcode()
    except (AttributeError, TypeError):
        value = None
    return value if isinstance(value, int) else 200


def _response_ray_id(response):
    return sanitize_text(_header(response, "CF-Ray"), 128)


def _decompress_once(raw, encoding, limit, diagnostic):
    def inflate(window_bits):
        decompressor = zlib.decompressobj(window_bits)
        output = decompressor.decompress(raw, limit + 1)
        if len(output) > limit or decompressor.unconsumed_tail:
            raise _response_error(
                "Cloudflare response exceeded the size limit",
                diagnostic,
                "response too large",
            )
        remaining = limit + 1 - len(output)
        output += decompressor.flush(remaining)
        if len(output) > limit:
            raise _response_error(
                "Cloudflare response exceeded the size limit",
                diagnostic,
                "response too large",
            )
        if not decompressor.eof:
            raise zlib.error("incomplete compressed response")
        return output

    try:
        if encoding in {"gzip", "x-gzip"}:
            return inflate(16 + zlib.MAX_WBITS)
        if encoding == "deflate":
            try:
                return inflate(zlib.MAX_WBITS)
            except zlib.error:
                return inflate(-zlib.MAX_WBITS)
    except zlib.error:
        raise _response_error(
            "Cloudflare returned invalid compressed data",
            diagnostic,
            "invalid compression",
        ) from None
    raise _response_error(
        "Cloudflare used an unsupported content encoding",
        diagnostic,
        "unsupported encoding",
    )


def _decode_content(raw, encoding, limit, diagnostic):
    encodings = [item.strip() for item in (encoding or "").split(",") if item.strip()]
    decoded = raw
    for item in reversed(encodings):
        if item == "identity":
            continue
        decoded = _decompress_once(decoded, item, limit, diagnostic)
    if len(decoded) > limit:
        raise _response_error(
            "Cloudflare response exceeded the size limit",
            diagnostic,
            "response too large",
        )
    return decoded


def _decode_bounded_json(raw, diagnostic=None):
    detail = diagnostic or ProviderDiagnostic()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        excerpt = sanitize_text(raw.decode("utf-8", "replace"), 512)
        raise _response_error(
            "Cloudflare response could not be read",
            replace(detail, excerpt=excerpt,
                    provider_message="malformed JSON response"),
            "malformed response",
        ) from None


def _base_diagnostic(response, request_id, *, status=None, response_size=None):
    return ProviderDiagnostic(
        status=_response_status(response) if status is None else status,
        request_id=request_id,
        content_type=_response_content_type(response),
        content_encoding=_response_content_encoding(response),
        response_size=response_size,
        ray_id=_response_ray_id(response),
    )


def _read_body(response, wire_limit, request_id, *, status=None):
    diagnostic = _base_diagnostic(response, request_id, status=status)
    raw = response.read(wire_limit + 1)
    diagnostic = replace(diagnostic, response_size=len(raw))
    if len(raw) > wire_limit:
        raise _response_error(
            "Cloudflare response exceeded the size limit",
            diagnostic,
            "response too large",
        )
    return raw, diagnostic


def _read_success_response(response, request_id):
    raw, diagnostic = _read_body(response, MAX_RESPONSE_BYTES, request_id)
    decoded = _decode_content(
        raw, diagnostic.content_encoding, MAX_RESPONSE_BYTES, diagnostic,
    )
    image_type = diagnostic.content_type in {"image/png", "image/jpeg", "image/jpg"}
    magic = decoded.startswith(b"\x89PNG\r\n\x1a\n") or decoded.startswith(b"\xff\xd8\xff")
    if image_type or magic:
        if not decoded or len(decoded) > MAX_IMAGE_BYTES:
            raise _response_error(
                "Cloudflare image exceeded the size limit",
                diagnostic,
                "response too large",
            )
        return _APIResponse(decoded, diagnostic)
    payload = _decode_bounded_json(decoded, diagnostic)
    return _APIResponse(payload, _with_provider(diagnostic, payload))


def _read_http_error(exc, request_id, reference):
    try:
        raw, diagnostic = _read_body(
            exc, MAX_ERROR_BYTES, request_id, status=exc.code,
        )
        decoded = _decode_content(
            raw, diagnostic.content_encoding, MAX_ERROR_BYTES, diagnostic,
        )
    except ImageGenerationError:
        raise
    except Exception:  # noqa: BLE001
        raw = b""
        decoded = b""
        diagnostic = _base_diagnostic(exc, request_id, status=exc.code, response_size=0)

    excerpt = sanitize_text(decoded.decode("utf-8", "replace"), 512)
    payload = None
    if decoded:
        try:
            candidate = json.loads(decoded.decode("utf-8"))
            if isinstance(candidate, dict):
                payload = candidate
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    diagnostic = replace(diagnostic, excerpt=excerpt)
    if payload is not None:
        diagnostic = _with_provider(diagnostic, payload)

    if exc.code in (401, 403):
        raise ImageAuthError(
            "Cloudflare authentication failed",
            replace(diagnostic, category="authentication failed"),
        ) from None
    if exc.code == 429:
        raise ImageQuotaError(
            "Cloudflare image quota is exhausted",
            replace(diagnostic, category="quota exhausted"),
        ) from None
    if reference and exc.code == 400:
        raise ImageReferenceError(
            "Cloudflare rejected the reference image",
            replace(diagnostic, category="reference rejected"),
        ) from None
    if payload is not None:
        _classify_api_error(
            payload, reference=reference, status=exc.code, diagnostic=diagnostic,
        )
    raise ImageResponseError(
        f"Cloudflare returned HTTP {exc.code}",
        replace(diagnostic, category="upstream error"),
    ) from None


def _read_api_response_details(request, timeout, reference=False, request_id=None):
    correlation_id = sanitize(
        {"request_id": request_id or new_request_id()},
    )["request_id"]
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _read_success_response(response, correlation_id)
    except urllib.error.HTTPError as exc:
        return _read_http_error(exc, correlation_id, reference)
    except (TimeoutError, socket.timeout):
        raise ImageTimeoutError(
            "Cloudflare image generation timed out",
            ProviderDiagnostic(category="timeout", request_id=correlation_id),
        ) from None
    except urllib.error.URLError:
        raise ImageResponseError(
            "Cloudflare response could not be read",
            ProviderDiagnostic(category="network error", request_id=correlation_id),
        ) from None


def _read_api_response(request, timeout, reference=False, request_id=None):
    return _read_api_response_details(
        request, timeout, reference, request_id,
    ).payload


def _read_json_response(request, timeout, reference=False, request_id=None):
    """Compatibility wrapper retained for callers that expect an envelope."""
    response = _read_api_response(request, timeout, reference, request_id)
    if isinstance(response, bytes):
        detail = ProviderDiagnostic(
            category="unexpected image response",
            request_id=request_id or "",
        )
        raise ImageResponseError(
            "Cloudflare returned image bytes where JSON was required", detail,
        )
    return response


def _load_reference_jpeg(url, timeout, request_id=None):
    correlation_id = request_id or new_request_id()
    if not is_reference_url(url):
        raise ImageResponseError(
            "Reference avatar is not hosted by Howdies",
            ProviderDiagnostic(
                category="invalid reference", request_id=correlation_id,
            ),
        )
    request = urllib.request.Request(url, headers={"User-Agent": "HowdiesBot/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_REFERENCE_BYTES + 1)
    except (TimeoutError, socket.timeout, urllib.error.URLError, urllib.error.HTTPError):
        raise ImageResponseError(
            "Reference avatar could not be downloaded",
            ProviderDiagnostic(
                category="reference download failed", request_id=correlation_id,
            ),
        ) from None
    if not raw or len(raw) > MAX_REFERENCE_BYTES:
        raise ImageResponseError(
            "Reference avatar exceeded the size limit",
            ProviderDiagnostic(
                category="reference too large", request_id=correlation_id,
                response_size=len(raw),
            ),
        )
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 25_000_000:
                raise ValueError("reference avatar dimensions are too large")
            image = image.convert("RGB")
            image.thumbnail((511, 511), Image.Resampling.LANCZOS)
            size = image.size
            output = BytesIO()
            image.save(output, "JPEG", quality=90, optimize=True)
            return _ReferenceImage(
                output.getvalue(), urlparse(url).hostname or "", size,
            )
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageResponseError(
            "Reference avatar was not a valid image",
            ProviderDiagnostic(
                category="invalid reference", request_id=correlation_id,
            ),
        ) from None


def _reference_jpeg(url, timeout):
    """Compatibility helper returning only the normalized JPEG bytes."""
    return _load_reference_jpeg(url, timeout).data


def _multipart(fields, files):
    boundary = f"howdies-{random.randint(1, 2_147_483_647)}"
    chunks = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            str(value).encode(), b"\r\n",
        ])
    for name, content in files:
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            (f'Content-Disposition: form-data; name="{name}"; '
             f'filename="{name}.jpg"\r\n').encode(),
            b"Content-Type: image/jpeg\r\n\r\n", content, b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _correlation_id(value):
    return sanitize({"request_id": value or new_request_id()})["request_id"]


def _generation_context(metadata, prompt):
    if isinstance(metadata, GenerationMetadata):
        context = asdict(metadata)
    elif isinstance(metadata, Mapping):
        context = {
            key: metadata.get(key, "")
            for key in (
                "requester_id", "requester_name", "room_id", "room_name",
                "original_prompt", "refined_prompt",
            )
        }
    else:
        context = {}
    context.setdefault("refined_prompt", prompt)
    if not context.get("refined_prompt"):
        context["refined_prompt"] = prompt
    return context


def _diagnostic_fields(diagnostic):
    if diagnostic is None:
        return {}
    return {
        "http_status": diagnostic.status,
        "content_type": diagnostic.content_type,
        "content_encoding": diagnostic.content_encoding,
        "response_size": diagnostic.response_size,
        "ray_id": diagnostic.ray_id,
        "provider_code": diagnostic.code,
        "provider_message": diagnostic.provider_message,
        "error_excerpt": diagnostic.excerpt,
    }


def _write_diagnostic(store, context, *, request_id, model, mode, outcome,
                      started_at, diagnostic=None, reference_images=()):
    if store is None:
        return
    record = {
        **context,
        "request_id": request_id,
        "model": model,
        "generation_mode": mode,
        "reference_avatar_domains": [item.domain for item in reference_images],
        "reference_avatar_dimensions": [list(item.size) for item in reference_images],
        "outcome": outcome,
        "elapsed_ms": max(0, round((time.monotonic() - started_at) * 1_000)),
        **_diagnostic_fields(diagnostic),
    }
    try:
        store.append(record)
    except Exception:  # noqa: BLE001 - diagnostics must not break image generation
        pass


def _error_outcome(error):
    if isinstance(error, ImageAuthError):
        return "authentication_error"
    if isinstance(error, ImageQuotaError):
        return "quota_error"
    if isinstance(error, ImageRejectedError):
        return "rejected"
    if isinstance(error, ImageTimeoutError):
        return "timeout"
    if isinstance(error, ImageReferenceError):
        return "reference_error"
    return "response_error"


def generate_image(prompt, account_id, api_token, timeout, *, request_id=None,
                   diagnostic_store=None, metadata=None):
    """Generate and validate one image, returning an owned temporary file."""
    correlation_id = _correlation_id(request_id)
    started_at = time.monotonic()
    context = _generation_context(metadata, prompt)
    if not _generation_lock.acquire(timeout):
        error = ImageTimeoutError(
            "Image generation is busy",
            ProviderDiagnostic(category="busy", request_id=correlation_id),
        )
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=TEXT_MODEL, mode="text", outcome="timeout",
            started_at=started_at, diagnostic=error.diagnostic,
        )
        raise error
    try:
        url = ("https://api.cloudflare.com/client/v4/accounts/"
               f"{account_id}/ai/run/{TEXT_MODEL}")
        payload = json.dumps({
            "prompt": prompt,
            "steps": 4,
            "seed": random.randint(1, 2_147_483_647),
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Authorization": f"Bearer {api_token}",
                     "Content-Type": "application/json"},
        )
        response = _read_api_response_details(
            request, timeout, request_id=correlation_id,
        )
        raw = (response.payload if isinstance(response.payload, bytes)
               else _decode_generated_image(
                   response.payload, diagnostic=response.diagnostic,
               ))
        generated = _save_generated_image(raw, response.diagnostic)
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=TEXT_MODEL, mode="text", outcome="success",
            started_at=started_at, diagnostic=response.diagnostic,
        )
        return generated
    except ImageGenerationError as error:
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=TEXT_MODEL, mode="text", outcome=_error_outcome(error),
            started_at=started_at, diagnostic=error.diagnostic,
        )
        raise
    except Exception as error:
        detail = ProviderDiagnostic(
            category="unexpected error",
            request_id=correlation_id,
            provider_message=type(error).__name__,
        )
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=TEXT_MODEL, mode="text", outcome="unexpected_error",
            started_at=started_at, diagnostic=detail,
        )
        raise
    finally:
        _generation_lock.release()


def generate_reference_image(prompt, avatar_urls, account_id, api_token, timeout, *,
                             request_id=None, diagnostic_store=None, metadata=None):
    """Generate a 512px image using up to two Howdies avatars as references."""
    correlation_id = _correlation_id(request_id)
    started_at = time.monotonic()
    context = _generation_context(metadata, prompt)
    if not 1 <= len(avatar_urls) <= 2:
        error = ImageResponseError(
            "Reference generation needs one or two avatars",
            ProviderDiagnostic(
                category="invalid reference", request_id=correlation_id,
            ),
        )
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=REFERENCE_MODEL, mode="reference", outcome="reference_error",
            started_at=started_at, diagnostic=error.diagnostic,
        )
        raise error
    if not _generation_lock.acquire(timeout):
        error = ImageTimeoutError(
            "Image generation is busy",
            ProviderDiagnostic(category="busy", request_id=correlation_id),
        )
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=REFERENCE_MODEL, mode="reference", outcome="timeout",
            started_at=started_at, diagnostic=error.diagnostic,
        )
        raise error
    references = []
    try:
        references = [
            _load_reference_jpeg(url, timeout, correlation_id)
            for url in avatar_urls
        ]
        body, content_type = _multipart(
            {"prompt": prompt, "width": 512, "height": 512, "seed":
             random.randint(1, 2_147_483_647)},
            [(f"input_image_{index}", avatar.data)
             for index, avatar in enumerate(references)],
        )
        url = ("https://api.cloudflare.com/client/v4/accounts/"
               f"{account_id}/ai/run/{REFERENCE_MODEL}")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Authorization": f"Bearer {api_token}",
                     "Content-Type": content_type},
        )
        response = _read_api_response_details(
            request, timeout, reference=True, request_id=correlation_id,
        )
        raw = (response.payload if isinstance(response.payload, bytes)
               else _decode_generated_image(
                   response.payload, reference=True,
                   diagnostic=response.diagnostic,
               ))
        generated = _save_generated_image(raw, response.diagnostic)
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=REFERENCE_MODEL, mode="reference", outcome="success",
            started_at=started_at, diagnostic=response.diagnostic,
            reference_images=references,
        )
        return generated
    except ImageGenerationError as error:
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=REFERENCE_MODEL, mode="reference",
            outcome=_error_outcome(error), started_at=started_at,
            diagnostic=error.diagnostic, reference_images=references,
        )
        raise
    except Exception as error:
        detail = ProviderDiagnostic(
            category="unexpected error",
            request_id=correlation_id,
            provider_message=type(error).__name__,
        )
        _write_diagnostic(
            diagnostic_store, context, request_id=correlation_id,
            model=REFERENCE_MODEL, mode="reference", outcome="unexpected_error",
            started_at=started_at, diagnostic=detail,
            reference_images=references,
        )
        raise
    finally:
        _generation_lock.release()


def remove_generated(image):
    try:
        os.unlink(image.path)
    except FileNotFoundError:
        pass
