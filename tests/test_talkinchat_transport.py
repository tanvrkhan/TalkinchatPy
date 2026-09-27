import asyncio
import unittest

from transports.talkinchat import (
    Capabilities,
    TalkinChatTransport,
    message_payload,
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

    def test_adapter_sends_json_and_reports_unsupported_capabilities(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        asyncio.run(transport.say("Room", "hello"))
        self.assertIsInstance(socket.sent[0], bytes)
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

    def test_room_text_is_bounded_before_it_reaches_websocket(self):
        socket = Socket()
        transport = TalkinChatTransport(socket, "bot", "pw", id_factory=lambda: "fixed")
        asyncio.run(transport.say("Room", "x" * 5000))
        fields = protobuf_fields(socket.sent[0])
        self.assertLessEqual(len(fields[5][0]), 900)
        self.assertTrue(fields[5][0].decode().endswith("..."))


if __name__ == "__main__":
    unittest.main()
