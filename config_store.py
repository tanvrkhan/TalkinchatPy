"""Atomic TalkinChat-only mutable configuration storage."""

import json
import os
from pathlib import Path


DEFAULTS = {
    "prefix": ",",
    "admins": [],
    "creator_aliases": [],
    "disabled": [],
    "rooms": [],
    "room_names": {},
    "welcome_rooms": {},
    "custom_welcomes": {},
    "welcome_images": {},
    "room_authorities": {},
    "cricket_rooms": {},
}


class ConfigStore:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "bot_config.json"
        self._state = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._state
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid TalkinChat configuration: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid TalkinChat configuration: expected object")
        self._state.update(value)
        return self._state

    def save(self):
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def get(self, key, default=None):
        return self._state.get(key, default)

    def set(self, key, value):
        if key in {"admins", "creator_aliases", "disabled"}:
            value = [str(item).casefold() for item in value]
        self._state[key] = value
        self.save()

    def prefix(self):
        return str(self.get("prefix", ","))
