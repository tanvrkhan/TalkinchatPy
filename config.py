"""Immutable environment-backed configuration for the TalkinChat runtime."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    pass


def _value(environ, name, default=""):
    return str(environ.get(name, default)).strip()


@dataclass(frozen=True)
class Config:
    username: str
    password: str = field(repr=False)
    rooms: tuple[str, ...]
    owner: str
    state_dir: Path = Path("/var/lib/talkinchat-bot")
    websocket_url: str = "wss://chatp.net:5333/server"
    upload_url: str = "https://cdn.talkinchat.com/post.php"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_lock: Path = Path("/run/lock/local-ollama.lock")
    connect_timeout: float = 15.0
    read_timeout: float = 90.0
    max_upload_bytes: int = 15 * 1024 * 1024
    collector_mode: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str]):
        username = _value(environ, "TALKINCHAT_USERNAME")
        password = _value(environ, "TALKINCHAT_PASSWORD")
        rooms = tuple(
            room.strip() for room in _value(environ, "TALKINCHAT_ROOM").split(",")
            if room.strip()
        )
        missing = []
        if not username:
            missing.append("TALKINCHAT_USERNAME")
        if not password:
            missing.append("TALKINCHAT_PASSWORD")
        if not rooms:
            missing.append("TALKINCHAT_ROOM")
        if missing:
            raise ConfigError("Missing required settings: " + ", ".join(missing))
        return cls(
            username=username,
            password=password,
            rooms=rooms,
            owner=_value(environ, "TALKINCHAT_OWNER", username),
            state_dir=Path(_value(environ, "TALKINCHAT_STATE_DIR", "/var/lib/talkinchat-bot")),
            websocket_url=_value(environ, "TALKINCHAT_WEBSOCKET_URL", "wss://chatp.net:5333/server"),
            upload_url=_value(environ, "TALKINCHAT_UPLOAD_URL", "https://cdn.talkinchat.com/post.php"),
            ollama_url=_value(environ, "TALKINCHAT_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=_value(environ, "TALKINCHAT_AI_MODEL", "llama3.2:3b"),
            ollama_lock=Path(_value(environ, "TALKINCHAT_OLLAMA_LOCK", "/run/lock/local-ollama.lock")),
            connect_timeout=float(_value(environ, "TALKINCHAT_CONNECT_TIMEOUT", "15")),
            read_timeout=float(_value(environ, "TALKINCHAT_READ_TIMEOUT", "90")),
            max_upload_bytes=int(_value(environ, "TALKINCHAT_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024))),
            collector_mode=_value(environ, "TALKINCHAT_MODE", "bot").casefold() == "collector",
        )


# Compatibility surface used by copied, protocol-free Howdies services.
# Every value is TalkinChat-owned; no Howdies environment or state is read.
OLLAMA_URL = os.environ.get("TALKINCHAT_OLLAMA_URL", "http://127.0.0.1:11434")
AI_MODEL = os.environ.get("TALKINCHAT_AI_MODEL", "llama3.2:3b")
AI_TIMEOUT = int(os.environ.get("TALKINCHAT_AI_TIMEOUT", "90"))
AI_BUSY_TIMEOUT = int(os.environ.get("TALKINCHAT_AI_BUSY_TIMEOUT", "25"))
AI_KEEP_ALIVE = os.environ.get("TALKINCHAT_AI_KEEP_ALIVE", "30m")
AI_LOCK_FILE = os.environ.get("TALKINCHAT_OLLAMA_LOCK", "/run/lock/local-ollama.lock")
IMAGE_LOCK_FILE = os.environ.get("TALKINCHAT_IMAGE_LOCK", "/tmp/talkinchat-image.lock")
