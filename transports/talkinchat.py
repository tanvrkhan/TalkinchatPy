"""Verified TalkinChat websocket and upload protocol boundary."""

import asyncio
import json
import secrets
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


def normalize_identity(value):
    return str(value or "").strip().casefold()


def login_payload(username, password, request_id):
    return {"handler": "login", "id": request_id, "username": username, "password": password}


def room_payload(handler, room, request_id):
    if handler not in {"room_join", "room_leave"}:
        raise ValueError("unsupported room handler")
    return {"handler": handler, "id": request_id, "name": room}


def message_payload(handler, target, kind, request_id, *, body="", url="", length=""):
    if handler not in {"room_message", "chat_message"}:
        raise ValueError("unsupported message handler")
    if kind not in {"text", "image", "audio"}:
        raise ValueError("unsupported message type")
    target_field = "room" if handler == "room_message" else "to"
    return {
        "handler": handler,
        "id": request_id,
        target_field: target,
        "type": kind,
        "url": url,
        "body": body,
        "length": length,
    }


class Capabilities(str, Enum):
    PRIVATE_MESSAGES = "private_messages"
    MEDIA = "media"
    ROOM_MEMBERSHIP = "room_membership"
    KICK = "kick"
    ROLES = "roles"
    PROFILE = "profile"
    BUTTONS = "buttons"
    MEMBER_LIST = "member_list"


SUPPORTED = frozenset({
    Capabilities.PRIVATE_MESSAGES,
    Capabilities.MEDIA,
    Capabilities.ROOM_MEMBERSHIP,
})


@dataclass(frozen=True)
class OperationResult:
    supported: bool
    message: str = ""


class EventKind(str, Enum):
    LOGIN_SUCCESS = "login_success"
    TEXT = "text"
    IMAGE = "image"
    USER_JOINED = "user_joined"
    UNKNOWN = "unknown"
    MALFORMED = "malformed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    event_id: str = ""
    room: str = ""
    user: str = ""
    user_key: str = ""
    body: str = ""
    url: str = ""
    raw_type: str = ""


class EventDecoder:
    def __init__(self, duplicate_window=1024):
        self._seen = set()
        self._order = deque(maxlen=duplicate_window)

    def decode(self, frame):
        try:
            if isinstance(frame, bytes):
                frame = frame.decode("utf-8")
            data = json.loads(frame)
            if not isinstance(data, dict):
                raise ValueError("event is not an object")
        except (UnicodeDecodeError, ValueError, TypeError):
            return Event(EventKind.MALFORMED)

        event_id = str(data.get("id") or "")
        if event_id and event_id in self._seen:
            return Event(EventKind.DUPLICATE, event_id=event_id)
        if event_id:
            if len(self._order) == self._order.maxlen:
                self._seen.discard(self._order[0])
            self._order.append(event_id)
            self._seen.add(event_id)

        handler = data.get("handler")
        event_type = str(data.get("type") or "")
        if handler == "login_event" and event_type == "success":
            kind = EventKind.LOGIN_SUCCESS
        elif handler == "room_event" and event_type == "text":
            kind = EventKind.TEXT
        elif handler == "room_event" and event_type == "image":
            kind = EventKind.IMAGE
        elif handler == "room_event" and event_type == "user_joined":
            kind = EventKind.USER_JOINED
        else:
            kind = EventKind.UNKNOWN
        user = str(data.get("from") or data.get("username") or "")
        return Event(
            kind=kind,
            event_id=event_id,
            room=str(data.get("room") or data.get("name") or ""),
            user=user,
            user_key=normalize_identity(user),
            body=str(data.get("body") or ""),
            url=str(data.get("url") or ""),
            raw_type=event_type,
        )


class TalkinChatTransport:
    def __init__(self, websocket, username, password, *, id_factory=None,
                 upload_url="https://cdn.talkinchat.com/post.php", max_upload_bytes=15 * 1024 * 1024):
        self.websocket = websocket
        self.username = username
        self._password = password
        self.id_factory = id_factory or (lambda: secrets.token_hex(10))
        self.upload_url = upload_url
        self.max_upload_bytes = max_upload_bytes

    def supports(self, capability):
        return capability in SUPPORTED

    async def _send(self, payload):
        await self.websocket.send(json.dumps(payload, separators=(",", ":")))
        return OperationResult(True)

    async def login(self):
        return await self._send(login_payload(self.username, self._password, self.id_factory()))

    async def join_room(self, room):
        return await self._send(room_payload("room_join", room, self.id_factory()))

    async def leave_room(self, room):
        return await self._send(room_payload("room_leave", room, self.id_factory()))

    async def rejoin_room(self, room, delay=1.0):
        await self.leave_room(room)
        await asyncio.sleep(delay)
        return await self.join_room(room)

    async def say(self, room, text):
        return await self._send(message_payload(
            "room_message", room, "text", self.id_factory(), body=str(text)))

    async def reply(self, room, text):
        return await self.say(room, text)

    async def send_dm(self, username, text):
        return await self._send(message_payload(
            "chat_message", username, "text", self.id_factory(), body=str(text)))

    async def send_image(self, room, url):
        return await self._send(message_payload(
            "room_message", room, "image", self.id_factory(), url=str(url)))

    async def send_audio(self, room, url, length=0):
        if float(length) > 600:
            raise ValueError("audio exceeds 600 second limit")
        return await self._send(message_payload(
            "room_message", room, "audio", self.id_factory(), url=str(url), length=str(length)))

    async def kick(self, room, username):
        return OperationResult(False, "Kick is not supported by the verified TalkinChat protocol.")

    async def room_members(self, room):
        return OperationResult(False, "Authoritative member lists are not supported by the verified protocol.")

    async def upload(self, path, room, mime_type, session=None):
        file_path = Path(path)
        size = file_path.stat().st_size
        if size > self.max_upload_bytes:
            raise ValueError("upload exceeds configured size limit")

        def post():
            import requests
            client = session or requests
            with file_path.open("rb") as handle:
                response = client.post(
                    self.upload_url,
                    files={"file": (file_path.name, handle, mime_type)},
                    data={"jid": self.username, "is_private": "no", "room": room,
                          "device_id": secrets.token_hex(8)},
                    timeout=30,
                )
            response.raise_for_status()
            return response.text.strip()

        return await asyncio.to_thread(post)
