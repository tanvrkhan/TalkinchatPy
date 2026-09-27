import asyncio
import json
import unittest

from transports.talkinchat import (
    Capabilities,
    TalkinChatTransport,
    login_payload,
    message_payload,
    room_payload,
)


class Socket:
    def __init__(self):
        self.sent = []

    async def send(self, value):
        self.sent.append(json.loads(value))


class PayloadTests(unittest.TestCase):
    def test_login_payload_uses_verified_fields(self):
        self.assertEqual(
            {"handler": "login", "id": "abc", "username": "bot", "password": "pw"},
            login_payload("bot", "pw", "abc"),
        )

    def test_room_payload_preserves_display_spelling(self):
        self.assertEqual(
            {"handler": "room_join", "id": "abc", "name": "My Room"},
            room_payload("room_join", "My Room", "abc"),
        )

    def test_message_payloads_match_verified_room_and_dm_contracts(self):
        self.assertEqual(
            {"handler": "room_message", "id": "1", "room": "My Room", "type": "text",
             "url": "", "body": "hello", "length": ""},
            message_payload("room_message", "My Room", "text", "1", body="hello"),
        )
        self.assertEqual(
            {"handler": "chat_message", "id": "2", "to": "Alice", "type": "image",
             "url": "https://image", "body": "", "length": ""},
            message_payload("chat_message", "Alice", "image", "2", url="https://image"),
        )

    def test_adapter_sends_json_and_reports_unsupported_capabilities(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        asyncio.run(transport.say("Room", "hello"))
        self.assertEqual("room_message", socket.sent[0]["handler"])
        self.assertFalse(transport.supports(Capabilities.KICK))
        result = asyncio.run(transport.kick("Room", "Alice"))
        self.assertFalse(result.supported)
        self.assertIn("not supported", result.message)
        self.assertEqual(1, len(socket.sent))

    def test_audio_length_is_bounded(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        with self.assertRaises(ValueError):
            asyncio.run(transport.send_audio("Room", "https://audio", 601))


if __name__ == "__main__":
    unittest.main()
