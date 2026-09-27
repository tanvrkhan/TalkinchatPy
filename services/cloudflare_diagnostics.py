"""Private, bounded diagnostics for Cloudflare image generation."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass


THREE_DAYS = 3 * 24 * 60 * 60
MAX_PAGE_SIZE = 20
MAX_RECORD_BYTES = 16 * 1024

DIAGNOSTIC_FIELDS = (
    "timestamp",
    "request_id",
    "requester_id",
    "requester_name",
    "room_id",
    "room_name",
    "original_prompt",
    "refined_prompt",
    "model",
    "generation_mode",
    "reference_avatar_domains",
    "reference_avatar_dimensions",
    "http_status",
    "content_type",
    "content_encoding",
    "response_size",
    "ray_id",
    "provider_code",
    "provider_message",
    "outcome",
    "elapsed_ms",
    "error_excerpt",
)

_TEXT_LIMITS = {
    "requester_id": 128,
    "requester_name": 128,
    "room_id": 128,
    "room_name": 128,
    "original_prompt": 1_000,
    "refined_prompt": 2_048,
    "model": 160,
    "generation_mode": 32,
    "content_type": 128,
    "content_encoding": 64,
    "ray_id": 128,
    "provider_code": 64,
    "provider_message": 512,
    "outcome": 64,
    "error_excerpt": 512,
}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)[\"']?\b(?:authorization|proxy-authorization|x-auth-key|api[_-]?(?:token|key)|"
    r"access[_-]?token|token|refresh[_-]?token|cookie|set-cookie|password|passwd|secret)"
    r"\b[\"']?\s*[:=]\s*"
    r"(?:bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]{8,})?\b")
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{80,}={0,2}(?![A-Za-z0-9+/=])")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def new_request_id():
    return f"cf-{uuid.uuid4().hex[:16]}"


def _truncate(value, limit):
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[:limit - 3] + "..."


def sanitize_text(value, limit=512):
    """Return one bounded line with credentials and encoded blobs removed."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.replace("\x00", " ").split())
    text = _SENSITIVE_ASSIGNMENT.sub("[redacted]", text)
    text = _BEARER.sub("[redacted]", text)
    text = _JWT.sub("[redacted]", text)
    text = _BASE64.sub("[base64 removed]", text)
    return _truncate(text, max(0, int(limit)))


def _finite_number(value, *, integer=False, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < minimum:
        return None
    return int(value) if integer else value


def _timestamp(value, now):
    parsed = _finite_number(value)
    return parsed if parsed is not None else now


def _request_id(value):
    if isinstance(value, str) and _REQUEST_ID.fullmatch(value):
        return value
    return new_request_id()


def _domains(value):
    if not isinstance(value, (list, tuple)):
        return []
    domains = []
    for item in value[:4]:
        clean = sanitize_text(item, 253).lower()
        if clean and re.fullmatch(r"[a-z0-9.-]+", clean):
            domains.append(clean)
    return domains


def _dimensions(value):
    if not isinstance(value, (list, tuple)):
        return []
    dimensions = []
    for item in value[:4]:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        width = _finite_number(item[0], integer=True, minimum=1)
        height = _finite_number(item[1], integer=True, minimum=1)
        if width is not None and height is not None:
            dimensions.append([min(width, 100_000), min(height, 100_000)])
    return dimensions


def sanitize(record, *, now=None):
    """Whitelist and bound one diagnostic record before it reaches disk."""
    source = record if isinstance(record, dict) else {}
    current = time.time() if now is None else now
    current = _finite_number(current) or time.time()
    clean = {
        "timestamp": _timestamp(source.get("timestamp"), current),
        "request_id": _request_id(source.get("request_id")),
        "requester_id": "",
        "requester_name": "",
        "room_id": "",
        "room_name": "",
        "original_prompt": "",
        "refined_prompt": "",
        "model": "",
        "generation_mode": "",
        "reference_avatar_domains": _domains(source.get("reference_avatar_domains")),
        "reference_avatar_dimensions": _dimensions(source.get("reference_avatar_dimensions")),
        "http_status": _finite_number(source.get("http_status"), integer=True, minimum=100),
        "content_type": "",
        "content_encoding": "",
        "response_size": _finite_number(source.get("response_size"), integer=True),
        "ray_id": "",
        "provider_code": "",
        "provider_message": "",
        "outcome": "",
        "elapsed_ms": _finite_number(source.get("elapsed_ms"), integer=True),
        "error_excerpt": "",
    }
    for field, limit in _TEXT_LIMITS.items():
        clean[field] = sanitize_text(source.get(field), limit)
    return clean


@dataclass(frozen=True)
class DiagnosticPage:
    records: tuple[dict, ...]
    page: int
    per_page: int
    total: int
    total_pages: int

    @property
    def has_previous(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.total_pages


class DiagnosticStore:
    """Process-safe JSONL storage with short retention and sanitized reads."""

    def __init__(self, path, *, retention_seconds=THREE_DAYS, cleanup_batch=200,
                 clock=time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
        self.retention_seconds = max(1, int(retention_seconds))
        self.cleanup_batch = max(1, min(int(cleanup_batch), 10_000))
        self._clock = clock
        self._thread_lock = threading.RLock()

    def _ensure_parent(self):
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)

    @contextmanager
    def _locked(self):
        self._ensure_parent()
        with self._thread_lock:
            descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def append(self, record):
        now = self._clock()
        clean = sanitize(record, now=now)
        encoded = (json.dumps(clean, ensure_ascii=True, allow_nan=False,
                              separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_RECORD_BYTES:
            raise ValueError("diagnostic record is too large")
        with self._locked():
            self._cleanup_locked(now, self.cleanup_batch)
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return clean

    def _load_lines(self):
        try:
            with open(self.path, "r", encoding="utf-8") as source:
                return source.readlines()
        except FileNotFoundError:
            return []

    @staticmethod
    def _parse_line(line):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return None
        return record if isinstance(record, dict) else None

    def _rewrite(self, lines):
        parent = os.path.dirname(os.path.abspath(self.path))
        descriptor, temporary = tempfile.mkstemp(prefix=".cloudflare-diag-", dir=parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                descriptor = None
                output.writelines(lines)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _cleanup_locked(self, now, limit):
        lines = self._load_lines()
        if not lines:
            return 0
        cutoff = now - self.retention_seconds
        kept = []
        removed = 0
        for line in lines:
            record = self._parse_line(line)
            timestamp = (_finite_number(record.get("timestamp"))
                         if record is not None else None)
            expired = record is None or timestamp is None or timestamp < cutoff
            if expired and removed < limit:
                removed += 1
                continue
            kept.append(line)
        if removed:
            self._rewrite(kept)
        elif os.path.exists(self.path):
            os.chmod(self.path, 0o600)
        return removed

    def cleanup(self, now=None):
        current = self._clock() if now is None else now
        current = _finite_number(current) or self._clock()
        with self._locked():
            return self._cleanup_locked(current, self.cleanup_batch)

    def failures(self, page, per_page=5):
        self.cleanup()
        current = _finite_number(self._clock())
        if current is None:
            current = time.time()
        cutoff = current - self.retention_seconds
        try:
            requested_page = max(1, int(page))
        except (TypeError, ValueError):
            requested_page = 1
        try:
            page_size = max(1, min(int(per_page), MAX_PAGE_SIZE))
        except (TypeError, ValueError):
            page_size = 5
        with self._locked():
            records = []
            for line in self._load_lines():
                record = self._parse_line(line)
                if record is None or record.get("outcome") == "success":
                    continue
                timestamp = _finite_number(record.get("timestamp"))
                if timestamp is None or timestamp < cutoff:
                    continue
                records.append(sanitize(record, now=record.get("timestamp")))
        records.sort(key=lambda item: item["timestamp"], reverse=True)
        total = len(records)
        total_pages = max(1, (total + page_size - 1) // page_size)
        selected_page = min(requested_page, total_pages)
        start = (selected_page - 1) * page_size
        return DiagnosticPage(
            records=tuple(records[start:start + page_size]),
            page=selected_page,
            per_page=page_size,
            total=total,
            total_pages=total_pages,
        )
