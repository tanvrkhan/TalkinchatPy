"""Shared file-locked persistence for cricket lobbies, queue, and matches."""

import copy
import fcntl
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class StoreError(ValueError):
    pass


class StoreConflict(StoreError):
    pass


class StaleRevision(StoreError):
    pass


class CricketStore:
    _guard = threading.Lock()
    _locks = {}

    def __init__(self, path, now=time.time):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        with self._guard:
            self._thread_lock = self._locks.setdefault(str(self.path), threading.RLock())

    @staticmethod
    def _empty():
        return {"version": 1, "lobbies": {}, "queue": [], "matches": {},
                "archives": {}, "claims": []}

    @contextmanager
    def _locked(self):
        with self._thread_lock:
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def save_lobby(self, lobby):
        room = str(lobby.get("room_id", ""))
        if not room:
            raise StoreError("Lobby requires a room ID.")
        with self._locked():
            state = self._read()
            if room in state["lobbies"] or self._room_in_match(state, room):
                raise StoreConflict("This room already has a cricket game.")
            incoming = self._human_keys(lobby)
            if incoming & self._active_human_keys(state):
                raise StoreConflict("A player is already in another cricket game.")
            state["lobbies"][room] = copy.deepcopy(lobby)
            self._write(state)
            return copy.deepcopy(lobby)

    def lobby(self, room_id):
        with self._locked():
            value = self._read()["lobbies"].get(str(room_id))
            return copy.deepcopy(value) if value is not None else None

    def update_lobby(self, room_id, callback):
        room = str(room_id)
        with self._locked():
            state = self._read()
            if room not in state["lobbies"]:
                raise StoreError("No cricket lobby exists in this room.")
            before = state["lobbies"].pop(room)
            candidate = callback(copy.deepcopy(before))
            incoming = self._human_keys(candidate)
            if incoming & self._active_human_keys(state):
                state["lobbies"][room] = before
                raise StoreConflict("A player is already in another cricket game.")
            state["lobbies"][room] = copy.deepcopy(candidate)
            self._write(state)
            return copy.deepcopy(candidate)

    def delete_lobby(self, room_id):
        room = str(room_id)
        with self._locked():
            state = self._read()
            existed = state["lobbies"].pop(room, None) is not None
            state["queue"] = [item for item in state["queue"] if item["room_id"] != room]
            if existed:
                self._write(state)
            return existed

    def queue_team(self, room_id):
        room = str(room_id)
        with self._locked():
            state = self._read()
            lobby = state["lobbies"].get(room)
            if lobby is None:
                raise StoreError("No cricket lobby exists in this room.")
            if len(lobby["players"]) != lobby["team_size"]:
                raise StoreConflict("The cricket team is not full yet.")
            if not any(item["room_id"] == room for item in state["queue"]):
                state["queue"].append({
                    "room_id": room,
                    "format": [lobby["team_size"], lobby["overs"], lobby["stake"]],
                    "queued_at": float(self._now()),
                })
                lobby["status"] = "queued"
                self._write(state)
            return copy.deepcopy(lobby)

    def pair_oldest(self):
        with self._locked():
            state = self._read()
            queue = sorted(state["queue"], key=lambda item: (item["queued_at"], item["room_id"]))
            pair = None
            for index, first in enumerate(queue):
                second = next((item for item in queue[index + 1:]
                               if item["format"] == first["format"]
                               and item["room_id"] != first["room_id"]), None)
                if second is not None:
                    pair = first, second
                    break
            if pair is None:
                return None
            first, second = pair
            match_id = uuid.uuid4().hex
            match = {
                "match_id": match_id, "revision": 1, "phase": "paired",
                "room_ids": [first["room_id"], second["room_id"]],
                "team_a": copy.deepcopy(state["lobbies"].pop(first["room_id"])),
                "team_b": copy.deepcopy(state["lobbies"].pop(second["room_id"])),
                "paired_at": float(self._now()),
            }
            paired_rooms = set(match["room_ids"])
            state["queue"] = [item for item in state["queue"]
                              if item["room_id"] not in paired_rooms]
            state["matches"][match_id] = copy.deepcopy(match)
            self._write(state)
            return match

    def save_match(self, match_id, snapshot):
        with self._locked():
            state = self._read()
            state["matches"][str(match_id)] = copy.deepcopy(snapshot)
            self._write(state)
            return True

    def load_match(self, match_id):
        with self._locked():
            value = self._read()["matches"].get(str(match_id))
            return copy.deepcopy(value) if value is not None else None

    def match_for_room(self, room_id):
        room = str(room_id)
        with self._locked():
            for match in self._read()["matches"].values():
                if match.get("phase") == "finished":
                    continue
                rooms = match.get("room_ids") or [
                    match.get("teams", {}).get("a", {}).get("room_id"),
                    match.get("teams", {}).get("b", {}).get("room_id"),
                ]
                if room in {str(value) for value in rooms if value is not None}:
                    return copy.deepcopy(match)
        return None

    def mutate_match(self, match_id, expected_revision, callback):
        key = str(match_id)
        with self._locked():
            state = self._read()
            current = state["matches"].get(key)
            if current is None:
                raise StoreError("Cricket match no longer exists.")
            if current.get("revision") != expected_revision:
                raise StaleRevision("Cricket match changed; refresh and try again.")
            candidate = callback(copy.deepcopy(current))
            if candidate.get("revision", 0) <= expected_revision:
                raise StoreError("Cricket mutation must advance its revision.")
            state["matches"][key] = copy.deepcopy(candidate)
            self._write(state)
            return copy.deepcopy(candidate)

    def archive_match(self, match_id, summary):
        key = str(match_id)
        with self._locked():
            state = self._read()
            if key in state["archives"]:
                return False
            if state["matches"].pop(key, None) is None:
                return False
            state["archives"][key] = copy.deepcopy(summary)
            self._write(state)
            return True

    def claim(self, key):
        key = str(key)
        with self._locked():
            state = self._read()
            if key in state["claims"]:
                return False
            state["claims"].append(key)
            self._write(state)
            return True

    def recover(self):
        with self._locked():
            state = self._read()
            return {name: copy.deepcopy(state[name]) for name in ("lobbies", "queue", "matches")}

    @staticmethod
    def _human_keys(container):
        return {str(player["key"]) for player in container.get("players", [])
                if not player.get("ai")}

    def _active_human_keys(self, state):
        keys = set()
        for lobby in state["lobbies"].values():
            keys |= self._human_keys(lobby)
        for match in state["matches"].values():
            if match.get("phase") == "finished":
                continue
            for team in (match.get("teams") or {}).values():
                keys |= self._human_keys(team)
            for name in ("team_a", "team_b"):
                keys |= self._human_keys(match.get(name) or {})
        return keys

    @staticmethod
    def _room_in_match(state, room):
        for match in state["matches"].values():
            if match.get("phase") == "finished":
                continue
            rooms = match.get("room_ids") or []
            if room in {str(value) for value in rooms}:
                return True
        return False

    def _read(self):
        if not self.path.exists():
            return self._empty()
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                state = json.load(stream)
        except (json.JSONDecodeError, UnicodeDecodeError):
            evidence = self.path.with_name(f"{self.path.name}.corrupt.{time.time_ns()}")
            os.replace(self.path, evidence)
            raise StoreError("Cricket state was corrupt and has been quarantined.")
        if not self._valid(state):
            raise StoreError("Cricket state schema is invalid.")
        return state

    @staticmethod
    def _valid(state):
        return (isinstance(state, dict) and state.get("version") == 1
                and isinstance(state.get("lobbies"), dict)
                and isinstance(state.get("queue"), list)
                and isinstance(state.get("matches"), dict)
                and isinstance(state.get("archives"), dict)
                and isinstance(state.get("claims"), list))

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
