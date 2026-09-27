import base64
import gzip
import io
import json
import os
import tempfile
import unittest
import urllib.error
import zlib
from unittest.mock import patch

from PIL import Image

from services.cloudflare_diagnostics import DiagnosticStore
from services import image_generation


class FakeResponse:
    def __init__(self, payload, content_type="application/json", *, headers=None,
                 status=200):
        self.payload = payload
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.payload


def image_payload():
    output = io.BytesIO()
    Image.new("RGB", (8, 6), "red").save(output, "JPEG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return json.dumps({"success": True, "result": {"image": encoded}}).encode()


class ImageGenerationTests(unittest.TestCase):
    def test_direct_png_response_is_accepted(self):
        output = io.BytesIO()
        Image.new("RGB", (5, 4), "green").save(output, "PNG")
        with patch.object(image_generation.urllib.request, "urlopen",
                          return_value=FakeResponse(output.getvalue(), "image/png")):
            generated = image_generation.generate_image(
                "green field", "account", "secret-token", timeout=12)
        try:
            self.assertEqual((5, 4), generated.size)
        finally:
            image_generation.remove_generated(generated)

    def test_valid_response_creates_verified_temporary_image(self):
        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append((request, timeout))
            return FakeResponse(image_payload())

        with patch.object(image_generation.urllib.request, "urlopen", fake_urlopen):
            generated = image_generation.generate_image(
                "red castle", "account", "secret-token", timeout=12)
        try:
            self.assertEqual((8, 6), generated.size)
            self.assertTrue(os.path.isfile(generated.path))
            self.assertIn("/accounts/account/ai/run/", requests[0][0].full_url)
            self.assertEqual("Bearer secret-token",
                             requests[0][0].get_header("Authorization"))
            self.assertEqual(12, requests[0][1])
        finally:
            image_generation.remove_generated(generated)
        self.assertFalse(os.path.exists(generated.path))

    def test_gzip_and_deflate_json_image_responses_are_accepted(self):
        for encoding, compressed in (
                ("gzip", gzip.compress(image_payload())),
                ("deflate", zlib.compress(image_payload()))):
            response = FakeResponse(
                compressed,
                headers={"Content-Encoding": encoding, "CF-Ray": "ray-compressed"},
            )
            with self.subTest(encoding=encoding), patch.object(
                    image_generation.urllib.request, "urlopen", return_value=response):
                generated = image_generation.generate_image(
                    "red castle", "account", "secret-token", timeout=12,
                    request_id=f"cf-{encoding}")
            try:
                self.assertEqual((8, 6), generated.size)
                self.assertEqual(f"cf-{encoding}", generated.request_id)
                self.assertEqual("ray-compressed", generated.diagnostic.ray_id)
                self.assertEqual(encoding, generated.diagnostic.content_encoding)
            finally:
                image_generation.remove_generated(generated)

    def test_malformed_json_keeps_request_and_response_metadata(self):
        response = FakeResponse(
            b'{"success": nope',
            headers={"CF-Ray": "ray-malformed"},
        )
        with patch.object(image_generation.urllib.request, "urlopen",
                          return_value=response):
            with self.assertRaises(image_generation.ImageResponseError) as caught:
                image_generation.generate_image(
                    "a private prompt", "account", "secret-token", 12,
                    request_id="cf-malformed")

        error = caught.exception
        self.assertEqual("cf-malformed", error.request_id)
        self.assertEqual("ray-malformed", error.diagnostic.ray_id)
        self.assertEqual("application/json", error.diagnostic.content_type)
        self.assertEqual(len(response.payload), error.diagnostic.response_size)
        self.assertIn("success", error.diagnostic.excerpt)
        self.assertNotIn("secret-token", error.diagnostic.excerpt)

    def test_compressed_http_provider_error_preserves_code_message_and_ray_id(self):
        payload = gzip.compress(json.dumps({
            "success": False,
            "errors": [{"code": 3036, "message": "daily neuron quota reached"}],
        }).encode())
        error = urllib.error.HTTPError(
            "https://example", 429, "failed",
            {"Content-Type": "application/json", "Content-Encoding": "gzip",
             "CF-Ray": "ray-quota"},
            io.BytesIO(payload),
        )

        with patch.object(image_generation.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(image_generation.ImageQuotaError) as caught:
                image_generation.generate_image(
                    "prompt", "account", "secret-token", 12,
                    request_id="cf-quota")

        self.assertEqual("cf-quota", caught.exception.request_id)
        self.assertEqual("3036", caught.exception.provider_code)
        self.assertEqual("daily neuron quota reached",
                         caught.exception.provider_message)
        self.assertEqual("ray-quota", caught.exception.diagnostic.ray_id)
        self.assertEqual("gzip", caught.exception.diagnostic.content_encoding)

    def test_text_http_error_is_bounded_sanitized_and_correlated(self):
        secret = "provider-secret-value"
        body = (f"Authorization: Bearer {secret} " + ("failure " * 500)).encode()
        error = urllib.error.HTTPError(
            "https://example", 502, "failed",
            {"Content-Type": "text/plain", "CF-Ray": "ray-text"},
            io.BytesIO(body),
        )

        with patch.object(image_generation.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(image_generation.ImageResponseError) as caught:
                image_generation.generate_image(
                    "prompt", "account", "api-token-value", 12,
                    request_id="cf-text")

        diagnostic = caught.exception.diagnostic
        self.assertEqual("cf-text", caught.exception.request_id)
        self.assertEqual("ray-text", diagnostic.ray_id)
        self.assertLessEqual(len(diagnostic.excerpt), 512)
        self.assertNotIn(secret, diagnostic.excerpt)
        self.assertNotIn("api-token-value", diagnostic.excerpt)

    def test_successful_generation_writes_only_safe_structured_diagnostic(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = os.path.join(tempdir, "cloudflare.jsonl")
            store = DiagnosticStore(path)
            metadata = image_generation.GenerationMetadata(
                requester_id="10450",
                requester_name="sherry",
                room_id="1253",
                room_name="Angels",
                original_prompt="draw me token=prompt-secret",
                refined_prompt="a detailed portrait",
            )
            response = FakeResponse(
                image_payload(),
                headers={"CF-Ray": "ray-success"},
            )
            with patch.object(image_generation.urllib.request, "urlopen",
                              return_value=response):
                generated = image_generation.generate_image(
                    "a detailed portrait", "account-secret", "api-token-secret", 12,
                    request_id="cf-success", diagnostic_store=store, metadata=metadata)
            image_generation.remove_generated(generated)

            with open(path, encoding="utf-8") as source:
                record = json.loads(source.readline())
            serialized = json.dumps(record)
            self.assertEqual("cf-success", record["request_id"])
            self.assertEqual("10450", record["requester_id"])
            self.assertEqual("text", record["generation_mode"])
            self.assertEqual("success", record["outcome"])
            self.assertEqual("ray-success", record["ray_id"])
            self.assertEqual("@cf/black-forest-labs/flux-1-schnell", record["model"])
            self.assertNotIn("prompt-secret", serialized)
            self.assertNotIn("account-secret", serialized)
            self.assertNotIn("api-token-secret", serialized)
            self.assertNotIn(base64.b64encode(b"image").decode(), serialized)

    def test_invalid_base64_is_rejected_without_leaking_token(self):
        payload = json.dumps({"success": True, "result": {"image": "%%%"}}).encode()
        with patch.object(image_generation.urllib.request, "urlopen",
                          return_value=FakeResponse(payload)):
            with self.assertRaises(image_generation.ImageResponseError) as caught:
                image_generation.generate_image("x", "account", "secret-token", 12)
        self.assertNotIn("secret-token", str(caught.exception))

    def test_non_image_bytes_are_rejected(self):
        encoded = base64.b64encode(b"not an image").decode("ascii")
        payload = json.dumps({"success": True, "result": {"image": encoded}}).encode()
        with patch.object(image_generation.urllib.request, "urlopen",
                          return_value=FakeResponse(payload)):
            with self.assertRaises(image_generation.ImageResponseError):
                image_generation.generate_image("x", "account", "token", 12)

    def test_temporary_file_failure_is_reported_as_invalid_response(self):
        with patch.object(image_generation.urllib.request, "urlopen",
                          return_value=FakeResponse(image_payload())), patch.object(
                              image_generation.tempfile, "NamedTemporaryFile",
                              side_effect=OSError("disk full")):
            with self.assertRaises(image_generation.ImageResponseError):
                image_generation.generate_image("x", "account", "token", 12)

    def test_http_errors_are_classified(self):
        for code, error_type in ((401, image_generation.ImageAuthError),
                                 (403, image_generation.ImageAuthError),
                                 (429, image_generation.ImageQuotaError)):
            error = urllib.error.HTTPError("https://example", code, "failed", {}, None)
            with self.subTest(code=code), patch.object(
                    image_generation.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(error_type):
                    image_generation.generate_image("x", "account", "token", 12)

    def test_provider_diagnostic_is_sanitized(self):
        body = io.BytesIO(json.dumps({
            "errors": [{"code": 1001, "message": "bad secret prompt details"}]
        }).encode())
        error = urllib.error.HTTPError("https://example", 400, "failed", {}, body)
        with patch.object(image_generation.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(image_generation.ImageResponseError) as caught:
                image_generation.generate_image("secret prompt", "account", "token", 12)
        diagnostic = image_generation.safe_diagnostic(caught.exception)
        self.assertIn("HTTP 400", diagnostic)
        self.assertIn("1001", diagnostic)
        self.assertNotIn("secret prompt", diagnostic)
        self.assertNotIn("token", diagnostic)

    def test_oversized_response_is_read_with_a_hard_limit(self):
        response = FakeResponse(b"x" * (image_generation.MAX_IMAGE_BYTES + 2), "text/html")
        with patch.object(image_generation.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(image_generation.ImageResponseError):
                image_generation.generate_image("x", "account", "token", 12)

    def test_compressed_body_cannot_expand_beyond_response_limit(self):
        payload = gzip.compress(b"x" * (image_generation.MAX_RESPONSE_BYTES + 1))
        response = FakeResponse(payload, "application/json",
                                headers={"Content-Encoding": "gzip"})
        with patch.object(image_generation.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(image_generation.ImageResponseError) as caught:
                image_generation.generate_image(
                    "x", "account", "token", 12, request_id="cf-zip-bomb")
        self.assertEqual("cf-zip-bomb", caught.exception.request_id)
        self.assertEqual("response too large", caught.exception.diagnostic.category)

    def test_timeout_is_classified(self):
        with patch.object(image_generation.urllib.request, "urlopen",
                          side_effect=TimeoutError()):
            with self.assertRaises(image_generation.ImageTimeoutError):
                image_generation.generate_image("x", "account", "token", 12)

    def test_reference_generation_uses_klein_multipart_with_avatar(self):
        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append((request, timeout))
            if request.full_url.startswith("https://cdn.talkinchat.com/"):
                avatar = io.BytesIO()
                Image.new("RGB", (700, 300), "blue").save(avatar, "PNG")
                return FakeResponse(avatar.getvalue())
            return FakeResponse(image_payload())

        with patch.object(image_generation.urllib.request, "urlopen", fake_urlopen):
            generated = image_generation.generate_reference_image(
                "place the person on Mars", ["https://cdn.talkinchat.com/avatar.png"],
                "account", "secret-token", timeout=20)
        try:
            request, timeout = requests[-1]
            self.assertIn("flux-2-klein-4b", request.full_url)
            self.assertEqual(20, timeout)
            self.assertTrue(request.get_header("Content-type").startswith("multipart/form-data;"))
            self.assertIn(b'name="input_image_0"', request.data)
            self.assertIn(b'name="width"', request.data)
            self.assertIn(b"512", request.data)
            self.assertEqual((8, 6), generated.size)
        finally:
            image_generation.remove_generated(generated)

    def test_reference_generation_records_only_avatar_domain_and_dimensions(self):
        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append((request, timeout))
            if request.full_url.startswith("https://cdn.talkinchat.com/"):
                avatar = io.BytesIO()
                Image.new("RGB", (700, 300), "blue").save(avatar, "PNG")
                return FakeResponse(avatar.getvalue(), "image/png")
            return FakeResponse(image_payload(), headers={"CF-Ray": "ray-reference"})

        with tempfile.TemporaryDirectory() as tempdir:
            store = DiagnosticStore(os.path.join(tempdir, "diagnostics.jsonl"))
            metadata = image_generation.GenerationMetadata(
                requester_id="10450",
                original_prompt="put @person on Mars",
                refined_prompt="put the referenced person on Mars",
            )
            avatar_url = "https://cdn.talkinchat.com/private/path/avatar.png?token=do-not-log"
            with patch.object(image_generation.urllib.request, "urlopen", fake_urlopen):
                generated = image_generation.generate_reference_image(
                    "put the referenced person on Mars", [avatar_url],
                    "account", "secret-token", timeout=20,
                    request_id="cf-reference", diagnostic_store=store,
                    metadata=metadata)
            image_generation.remove_generated(generated)

            with open(store.path, encoding="utf-8") as source:
                record = json.loads(source.readline())
            serialized = json.dumps(record)
            self.assertEqual("reference", record["generation_mode"])
            self.assertEqual(["cdn.talkinchat.com"], record["reference_avatar_domains"])
            self.assertEqual([[511, 219]], record["reference_avatar_dimensions"])
            self.assertNotIn("private/path", serialized)
            self.assertNotIn("do-not-log", serialized)
            self.assertNotIn("secret-token", serialized)

    def test_json_data_uri_image_is_accepted(self):
        payload = json.loads(image_payload())
        payload["result"]["image"] = (
            "data:image/jpeg;charset=utf-8;base64," + payload["result"]["image"])
        with patch.object(
                image_generation.urllib.request, "urlopen",
                return_value=FakeResponse(json.dumps(payload).encode())):
            generated = image_generation.generate_image(
                "red castle", "account", "token", 12,
                request_id="cf-data-uri")
        try:
            self.assertEqual((8, 6), generated.size)
        finally:
            image_generation.remove_generated(generated)

    def test_reference_generation_rejects_non_talkinchat_avatar_url(self):
        with self.assertRaises(image_generation.ImageResponseError):
            image_generation.generate_reference_image(
                "prompt", ["https://example.com/avatar.png"],
                "account", "token", timeout=12)

    def test_reference_avatar_is_resized_strictly_below_512(self):
        avatar = io.BytesIO()
        Image.new("RGB", (900, 400), "blue").save(avatar, "PNG")
        with patch.object(image_generation.urllib.request, "urlopen",
                          return_value=FakeResponse(avatar.getvalue())):
            encoded = image_generation._reference_jpeg(
                "https://cdn.talkinchat.com/avatar.png", timeout=12)

        with Image.open(io.BytesIO(encoded)) as resized:
            self.assertLess(resized.width, 512)
            self.assertLess(resized.height, 512)

    def test_reference_http_400_is_classified_separately(self):
        avatar = io.BytesIO()
        Image.new("RGB", (100, 100), "blue").save(avatar, "PNG")
        responses = iter((FakeResponse(avatar.getvalue()),
                          urllib.error.HTTPError("https://example", 400,
                                                 "failed", {}, None)))

        def fake_urlopen(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        with patch.object(image_generation.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(image_generation.ImageReferenceError):
                image_generation.generate_reference_image(
                    "prompt", ["https://cdn.talkinchat.com/avatar.png"],
                    "account", "token", timeout=12)


if __name__ == "__main__":
    unittest.main()
