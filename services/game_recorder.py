"""Creator-controlled capture of public room game traffic."""

import json
import os
import re
import time
from pathlib import Path


class GameRecorder:
    def __init__(self, directory, now=time.time):
        self.directory = Path(directory)
        self._now = now
        self._sessions = {}

    @staticmethod
    def _room_key(room_id):
        return str(room_id)

    @staticmethod
    def _safe_name(value):
        return re.sub(r"[^a-z0-9_-]+", "-", str(value).strip().lower()).strip("-") or "game"

    @staticmethod
    def _append(path, record):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def start(self, room_id, target, game, creator):
        key = self._room_key(room_id)
        if key in self._sessions:
            raise ValueError("A game recording is already active in this room.")
        self.directory.mkdir(parents=True, exist_ok=True)
        started_at = float(self._now())
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started_at))
        millis = int(started_at * 1000) % 1000
        path = self.directory / (
            f"{self._safe_name(game)}-{key}-{stamp}-{millis:03d}.jsonl"
        )
        session = {
            "room_id": key,
            "target": str(target).strip().lstrip("@").casefold(),
            "game": str(game).strip().casefold(),
            "creator": str(creator),
            "started_at": started_at,
            "events": 0,
            "path": str(path),
        }
        self._sessions[key] = session
        self._append(path, {"kind": "start", **session})
        return dict(session)

    def status(self, room_id):
        session = self._sessions.get(self._room_key(room_id))
        return dict(session) if session else None

    def record(self, frame):
        if (not isinstance(frame, dict)
                or frame.get("secret") in (True, 1, "1", "true", "True")):
            return False
        room_id = frame.get("roomid")
        session = self._sessions.get(self._room_key(room_id))
        if session is None or str(frame.get("handler", "")).casefold() == "message":
            return False
        self._append(session["path"], {
            "kind": "frame", "received_at": float(self._now()), "frame": frame,
        })
        session["events"] += 1
        return True

    def stop(self, room_id):
        key = self._room_key(room_id)
        session = self._sessions.pop(key, None)
        if session is None:
            raise ValueError("No game recording is active in this room.")
        result = dict(session)
        self._append(session["path"], {
            "kind": "stop", "stopped_at": float(self._now()),
            "events": session["events"],
        })
        return result
