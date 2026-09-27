"""Atomic cricket-specific career statistics."""

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


class CricketStats:
    _guard = threading.Lock()
    _locks = {}

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        with self._guard:
            self._thread_lock = self._locks.setdefault(str(self.path), threading.RLock())

    @contextmanager
    def _locked(self):
        with self._thread_lock:
            with open(self._lock_path, "a+", encoding="utf-8") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _empty():
        return {"version": 1, "players": {}, "claims": []}

    def apply_match(self, summary, key):
        with self._locked():
            state = self._read()
            if str(key) in state["claims"]:
                return False
            for item in summary.get("players", []):
                uid = str(item.get("userid", ""))
                if not uid:
                    continue
                record = state["players"].setdefault(uid, {
                    "userid": uid, "user": item.get("user", uid), "matches": 0,
                    "wins": 0, "losses": 0, "ties": 0, "runs": 0, "balls": 0,
                    "wickets": 0, "runs_conceded": 0, "best_score": 0,
                    "best_bowling": 0, "streak": 0, "rating": 1000,
                })
                won = item.get("team") == summary.get("winner")
                tied = summary.get("winner") is None
                record["user"] = item.get("user", record["user"])
                record["matches"] += 1
                record["wins"] += int(won)
                record["losses"] += int(not won and not tied)
                record["ties"] += int(tied)
                record["runs"] += int(item.get("runs", 0))
                record["balls"] += int(item.get("balls", 0))
                record["wickets"] += int(item.get("wickets", 0))
                record["runs_conceded"] += int(item.get("runs_conceded", 0))
                record["best_score"] = max(record["best_score"], int(item.get("runs", 0)))
                record["best_bowling"] = max(record["best_bowling"], int(item.get("wickets", 0)))
                record["streak"] = record["streak"] + 1 if won else 0
                record["rating"] = max(0, record["rating"] + (20 if won else -10 if not tied else 0))
            state["claims"].append(str(key))
            self._write(state)
            return True

    def player(self, user_id):
        with self._locked():
            record = dict(self._read()["players"].get(str(user_id), {}))
        if record:
            record["strike_rate"] = round(
                record["runs"] * 100 / record["balls"], 2
            ) if record["balls"] else 0.0
            record["economy"] = round(
                record["runs_conceded"] * 6 / max(1, record["balls"]), 2
            )
        return record

    def leaderboard(self, metric="rating", limit=10, offset=0):
        allowed = {"rating", "wins", "runs", "wickets", "matches", "streak"}
        metric = metric if metric in allowed else "rating"
        with self._locked():
            records = list(self._read()["players"].values())
        records.sort(key=lambda item: (-int(item.get(metric, 0)), item.get("user", "").casefold()))
        return records[int(offset):int(offset) + int(limit)]

    def _read(self):
        if not self.path.exists():
            return self._empty()
        with self.path.open("r", encoding="utf-8") as stream:
            state = json.load(stream)
        if (not isinstance(state, dict) or state.get("version") != 1
                or not isinstance(state.get("players"), dict)
                or not isinstance(state.get("claims"), list)):
            raise ValueError("Cricket statistics schema is invalid.")
        return state

    def _write(self, state):
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
