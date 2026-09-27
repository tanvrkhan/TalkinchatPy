"""Verified TalkinChat websocket and upload protocol boundary."""

import asyncio
import base64
import json
import secrets
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


def normalize_identity(value):
    return str(value or "").strip().casefold()


def _varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _string_field(number, value):
    value = str(value).encode("utf-8")
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _integer_field(number, value):
    return _varint(number << 3) + _varint(int(value))


def _read_varint(payload, offset):
    value = shift = 0
    while offset < len(payload):
        byte = payload[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
        shift += 7
        if shift > 63:
            break
    raise ValueError("invalid protobuf varint")


def protobuf_fields(payload):
    """Decode the wire types used by TalkinChat while preserving repeated fields."""
    fields = {}
    offset = 0
    while offset < len(payload):
        tag, offset = _read_varint(payload, offset)
        number, wire_type = tag >> 3, tag & 7
        if not number:
            raise ValueError("invalid protobuf field")
        if wire_type == 0:
            value, offset = _read_varint(payload, offset)
        elif wire_type == 2:
            length, offset = _read_varint(payload, offset)
            end = offset + length
            if end > len(payload):
                raise ValueError("truncated protobuf field")
            value, offset = payload[offset:end], end
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")
        fields.setdefault(number, []).append(value)
    return fields


def _text(fields, number):
    values = fields.get(number, ())
    if not values or not isinstance(values[0], bytes):
        return ""
    return values[0].decode("utf-8", errors="replace")


def build_auth_request(username, password, *, sid=None, device_id=None,
                       device_model="444$Python-Bot$34", language="en"):
    values = {
        1: "login", 2: username, 3: password, 4: "", 5: "",
        6: sid or str(uuid.uuid4()), 7: "34", 8: "android@",
        9: "444", 10: "2", 11: device_id or str(uuid.uuid4()),
        12: device_model, 13: language, 14: "1",
    }
    return b"".join(_string_field(number, value) for number, value in values.items())


@dataclass(frozen=True)
class AuthResult:
    result: str
    user_id: str
    captcha_id: str
    message: str
    server: str
    method: str
    photo_version: str = ""


def parse_auth_result(payload):
    fields = protobuf_fields(payload)
    return AuthResult(
        _text(fields, 1), _text(fields, 2), _text(fields, 5),
        _text(fields, 6), _text(fields, 7), _text(fields, 8), _text(fields, 4),
    )


def authenticate(auth_url, username, password, *, device_id, session=None, timeout=15):
    client = session
    if client is None:
        import requests
        client = requests
    payload = build_auth_request(username, password, device_id=device_id)
    response = client.post(
        auth_url, data=payload, headers={"Content-Type": "application/octet-stream"},
        timeout=timeout,
    )
    response.raise_for_status()
    result = parse_auth_result(response.content)
    if result.result != "ok":
        raise PermissionError(result.message or "TalkinChat authentication failed")
    if not result.server.isdigit():
        raise ValueError("TalkinChat authentication returned an invalid server")
    return result


def websocket_headers(username, password, auth, *, device_id, device_model="444$Python-Bot$34"):
    encode = lambda value: base64.b64encode(str(value).encode()).decode()
    if auth.method == "n":
        token = "@".join((auth.captcha_id, device_id, device_model, "android", "en",
                          auth.photo_version, ""))
        return {"b": encode(token)}
    return {
        "action": "login", "os": "android", "api_ver": "2", "client_ver": "1",
        "username": encode(username), "password": encode(password),
        "captcha_text": encode(""), "captcha_id": encode(auth.captcha_id),
        "captcha_url": encode(""), "m": encode(device_model), "i": encode(device_id),
        "ver": encode("444"), "sdk": encode("34"),
    }


def room_payload(handler, room, request_id):
    if handler not in {"room_join", "room_leave"}:
        raise ValueError("unsupported room handler")
    action = handler
    payload = _string_field(1, action) + _string_field(6, room)
    if handler == "room_join":
        payload += _string_field(9, "") + _integer_field(13, 0)
    return payload


def message_payload(handler, target, kind, request_id, *, body="", url="", length=""):
    if handler not in {"room_message", "chat_message"}:
        raise ValueError("unsupported message handler")
    if kind not in {"text", "image", "audio"}:
        raise ValueError("unsupported message type")
    fields = [_string_field(1, handler), _string_field(2, kind)]
    if length != "":
        fields.append(_string_field(3, length))
    fields.append(_string_field(4 if handler == "chat_message" else 6, target))
    if body:
        fields.append(_string_field(5, body))
    if url:
        fields.append(_string_field(7, url))
    return b"".join(fields)


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
MAX_TEXT_BYTES = 900


def _bounded_text(value):
    encoded = str(value).encode("utf-8")
    if len(encoded) <= MAX_TEXT_BYTES:
        return str(value)
    return encoded[:MAX_TEXT_BYTES - 3].decode("utf-8", errors="ignore") + "..."


@dataclass(frozen=True)
class OperationResult:
    supported: bool
    message: str = ""


class EventKind(str, Enum):
    LOGIN_SUCCESS = "login_success"
    TEXT = "text"
    DIRECT_TEXT = "direct_text"
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
    avatar: str = ""


class EventDecoder:
    def __init__(self, duplicate_window=1024):
        self._seen = set()
        self._order = deque(maxlen=duplicate_window)

    def decode(self, frame):
        if isinstance(frame, bytes):
            if frame.lstrip().startswith((b"{", b"[")):
                try:
                    frame = frame.decode("utf-8")
                except UnicodeDecodeError:
                    return Event(EventKind.MALFORMED)
            else:
                try:
                    return self._decode_binary(frame)
                except (ValueError, TypeError):
                    return Event(EventKind.MALFORMED)
        try:
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
        elif handler in {"chat_event", "chat_message"} and event_type == "text":
            kind = EventKind.DIRECT_TEXT
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
            avatar=str(data.get("avatarUrl") or data.get("avatar_url") or ""),
        )

    def _decode_binary(self, frame):
        result = protobuf_fields(frame)
        handler_id = result.get(1, [0])[0]
        if handler_id == 16:
            return Event(EventKind.LOGIN_SUCCESS)
        if handler_id == 12 and 9 in result:
            message = protobuf_fields(result[9][0])
            event_type = _text(message, 1)
            user = _text(message, 3)
            return Event(
                kind=(EventKind.DIRECT_TEXT if event_type == "text"
                      else EventKind.UNKNOWN),
                event_id=_text(message, 2), user=user,
                user_key=normalize_identity(user), body=_text(message, 5),
                url=_text(message, 6), raw_type=event_type,
            )
        if handler_id != 6 or 10 not in result:
            return Event(EventKind.UNKNOWN)
        room_event = protobuf_fields(result[10][0])
        event_type = _text(room_event, 1)
        kinds = {
            "text": EventKind.TEXT,
            "image": EventKind.IMAGE,
            "user_joined": EventKind.USER_JOINED,
            "joined": EventKind.USER_JOINED,
        }
        user = _text(room_event, 2) or _text(room_event, 22)
        return Event(
            kind=kinds.get(event_type, EventKind.UNKNOWN),
            event_id=_text(room_event, 41), room=_text(room_event, 13),
            user=user, user_key=normalize_identity(user), body=_text(room_event, 6),
            url=_text(room_event, 7), raw_type=event_type,
            avatar=_text(room_event, 10),
        )


class TalkinChatTransport:
    def __init__(self, websocket, username, password, *, id_factory=None,
                 upload_url="https://talkinchat.com/upload", max_upload_bytes=15 * 1024 * 1024):
        self.websocket = websocket
        self.username = username
        self._password = password
        self.id_factory = id_factory or (lambda: secrets.token_hex(10))
        self.upload_url = upload_url
        self.max_upload_bytes = max_upload_bytes

    def supports(self, capability):
        return capability in SUPPORTED

    async def _send(self, payload):
        await self.websocket.send(payload)
        return OperationResult(True)

    async def login(self):
        return OperationResult(True)

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
            "room_message", room, "text", self.id_factory(), body=_bounded_text(text)))

    async def reply(self, room, text):
        return await self.say(room, text)

    async def send_dm(self, username, text):
        return await self._send(message_payload(
            "chat_message", username, "text", self.id_factory(), body=_bounded_text(text)))

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
