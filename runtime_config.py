"""Validated process configuration for the TalkinChat runtime."""

from dataclasses import dataclass, field
from typing import Mapping


class RuntimeConfigError(ValueError):
    """Raised when required TalkinChat runtime settings are absent."""


@dataclass(frozen=True)
class RuntimeConfig:
    username: str
    password: str = field(repr=False)
    room: str
    owner: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "RuntimeConfig":
        username = environ.get("TALKINCHAT_USERNAME", "").strip()
        password = environ.get("TALKINCHAT_PASSWORD", "").strip()
        room = environ.get("TALKINCHAT_ROOM", "").strip()
        owner = environ.get("TALKINCHAT_OWNER", "").strip() or username
        return cls(username=username, password=password, room=room, owner=owner)

    def require_valid(self) -> "RuntimeConfig":
        values = {
            "TALKINCHAT_USERNAME": self.username,
            "TALKINCHAT_PASSWORD": self.password,
            "TALKINCHAT_ROOM": self.room,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeConfigError(
                "Missing required environment variables: " + ", ".join(missing)
            )
        return self
