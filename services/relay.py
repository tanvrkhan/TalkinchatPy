"""Private filesystem relay for commands between bot processes."""

import json
import os
import secrets
import time
from pathlib import Path


REQUEST_OPERATIONS = {"creator_command", "connect_request"}


class RelayStore:
    def __init__(self, root, now=time.time):
        self.root = Path(root)
        self.requests = self.root / "requests"
        self.results = self.root / "results"
        self.now = now
        self.requests.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(value):
        return str(value or "").strip().casefold()

    @staticmethod
    def _valid_base(envelope):
        return (isinstance(envelope, dict)
                and envelope.get("version") == 1
                and isinstance(envelope.get("id"), str)
                and isinstance(envelope.get("target"), str)
                and isinstance(envelope.get("expires_at"), (int, float)))

    def _write(self, directory, name, envelope):
        path = directory / f"{name}.json"
        temporary = directory / f".{name}.{secrets.token_hex(6)}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return path

    def submit(self, operation, target, sender, sender_id, payload, ttl=60):
        if operation not in REQUEST_OPERATIONS:
            raise ValueError("unsupported relay operation")
        if not isinstance(payload, dict):
            raise ValueError("relay payload must be an object")
        now = float(self.now())
        request_id = secrets.token_hex(16)
        self._write(self.requests, request_id, {
            "version": 1, "id": request_id, "operation": operation,
            "target": self._key(target), "sender": self._key(sender),
            "sender_id": sender_id, "created_at": now,
            "expires_at": now + ttl, "payload": payload,
        })
        return request_id

    def submit_result(self, request_id, target, sender, sender_id, messages,
                      error=None, source=""):
        now = float(self.now())
        result_id = f"{request_id}-{secrets.token_hex(6)}"
        self._write(self.results, result_id, {
            "version": 1, "id": request_id, "target": self._key(target),
            "sender": self._key(sender), "sender_id": sender_id,
            "source": self._key(source), "created_at": now,
            "expires_at": now + 60, "messages": [str(m) for m in messages],
            "error": str(error) if error else None,
        })

    def _claim(self, directory, target, result=False):
        claimed = []
        now = float(self.now())
        target = self._key(target)
        for path in sorted(directory.glob("*.json")):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
                continue
            valid = self._valid_base(envelope)
            if not result:
                valid = (valid and envelope.get("operation") in REQUEST_OPERATIONS
                         and isinstance(envelope.get("payload"), dict))
            if not valid or envelope["expires_at"] <= now:
                path.unlink(missing_ok=True)
                continue
            if self._key(envelope["target"]) != target:
                continue
            claim = path.with_suffix(".claimed")
            try:
                os.replace(path, claim)
            except FileNotFoundError:
                continue
            try:
                claimed.append(envelope)
            finally:
                claim.unlink(missing_ok=True)
        return claimed

    def claim_requests(self, target):
        return self._claim(self.requests, target)

    def claim_results(self, target):
        return self._claim(self.results, target, result=True)

    def cleanup(self):
        for directory in (self.requests, self.results):
            self._claim(directory, "__cleanup_never_matches__")
