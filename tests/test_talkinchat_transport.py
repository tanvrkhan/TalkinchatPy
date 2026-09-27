import asyncio
import unittest

from transports.talkinchat import (
    Capabilities,
    TalkinChatTransport,
    message_payload,
    moderation_payload,
    room_payload,
    protobuf_fields,
)


class Socket:
    def __init__(self):
        self.sent = []

    async def send(self, value):
        self.sent.append(value)


class PayloadTests(unittest.TestCase):
    def test_room_payload_preserves_display_spelling(self):
        self.assertIsInstance(room_payload("room_join", "My Room", "abc"), bytes)

    def test_message_payloads_match_verified_room_and_dm_contracts(self):
        self.assertIsInstance(message_payload(
            "room_message", "My Room", "text", "1", body="hello"), bytes)
        self.assertIsInstance(message_payload(
            "chat_message", "Alice", "image", "2", url="https://image"), bytes)

    def test_adapter_sends_messages_and_verified_moderation_payloads(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        asyncio.run(transport.say("Room", "hello"))
        self.assertIsInstance(socket.sent[0], bytes)
        self.assertTrue(transport.supports(Capabilities.KICK))
        self.assertTrue(transport.supports(Capabilities.ROLES))
        result = asyncio.run(transport.kick("Room", "Alice"))
        self.assertTrue(result.supported)
        self.assertEqual(
            {1: [b"room_admin"], 2: [b"kick"], 4: [b"Alice"],
             6: [b"Room"], 11: [b"none"]},
            protobuf_fields(socket.sent[-1]),
        )
        asyncio.run(transport.set_role("Room", "Bob", "owner"))
        self.assertEqual(
            {1: [b"room_admin"], 2: [b"change_role"], 4: [b"Bob"],
             6: [b"Room"], 11: [b"owner"]},
            protobuf_fields(socket.sent[-1]),
        )

    def test_moderation_payload_rejects_missing_targets_and_unknown_roles(self):
        with self.assertRaises(ValueError):
            moderation_payload("kick", "Room", "")
        with self.assertRaises(ValueError):
            moderation_payload("change_role", "Room", "Alice", "moderator")

    def test_audio_length_is_bounded(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        with self.assertRaises(ValueError):
            asyncio.run(transport.send_audio("Room", "https://audio", 601))

    def test_room_text_is_bounded_before_it_reaches_websocket(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        asyncio.run(transport.say("Room", "x" * 5000))
        fields = protobuf_fields(socket.sent[0])
        self.assertLessEqual(len(fields[5][0]), 900)
        self.assertTrue(fields[5][0].decode().endswith("..."))


if __name__ == "__main__":
    unittest.main()
