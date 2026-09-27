"""Atomic durable storage for resumable room games."""

import copy
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import fcntl


_VERSION = 1


class GameStore:
    """Store game snapshots and reward claims in one versioned JSON document."""

    _locks_guard = threading.Lock()
    _locks = {}

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = self._lock_for(self.path)
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    @classmethod
    def _lock_for(cls, path):
        key = os.fspath(path)
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _empty_state():
        return {"version": _VERSION, "games": {}, "claimed_rewards": []}

    @contextmanager
    def _locked(self):
        with self._thread_lock:
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def load_all(self):
        with self._locked():
            state = self._read_locked()
            return copy.deepcopy(state["games"]) if state is not None else {}

    def save(self, room_id, snapshot):
        with self._locked():
            state = self._read_locked()
            if state is None:
                return False
            state["games"][str(room_id)] = snapshot
            self._write_atomic(state)
            return True

    def delete(self, room_id):
        with self._locked():
            state = self._read_locked()
            if state is None:
                return False
            room_id = str(room_id)
            if room_id not in state["games"]:
                return False
            del state["games"][room_id]
            self._write_atomic(state)
            return True

    def claim_reward(self, key):
        with self._locked():
            state = self._read_locked()
            if state is None:
                return False
            key = str(key)
            if key in state["claimed_rewards"]:
                return False
            state["claimed_rewards"].append(key)
            self._write_atomic(state)
            return True

    def _read_locked(self):
        if not self.path.exists():
            return None if self._corrupt_copies() else self._empty_state()
        try:
            with self.path.open("r", encoding="utf-8") as state_file:
                state = json.load(state_file)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._quarantine_locked()
            return None
        if not self._valid_state(state):
            self._quarantine_locked()
            return None
        return state

    @staticmethod
    def _valid_state(state):
        return (
            isinstance(state, dict)
            and type(state.get("version")) is int
            and state["version"] == _VERSION
            and isinstance(state.get("games"), dict)
            and all(isinstance(room_id, str) for room_id in state["games"])
            and isinstance(state.get("claimed_rewards"), list)
            and all(isinstance(key, str) for key in state["claimed_rewards"])
        )

    def _corrupt_copies(self):
        return list(self.path.parent.glob(f"{self.path.name}.corrupt.*"))

    def _quarantine_locked(self):
        evidence = self.path.with_name(
            f"{self.path.name}.corrupt.{time.time_ns()}"
        )
        os.replace(self.path, evidence)

    def _write_atomic(self, state):
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
                json.dump(state, state_file, ensure_ascii=True,
                          separators=(",", ":"), sort_keys=True, allow_nan=False)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self.path)
            self._fsync_directory()
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _fsync_directory(self):
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
