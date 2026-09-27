import json
import unittest

from transports.talkinchat import EventDecoder, EventKind, normalize_identity


class EventTests(unittest.TestCase):
    def test_normalizes_verified_room_events(self):
        decoder = EventDecoder()
        event = decoder.decode(json.dumps({
            "handler": "room_event", "id": "evt-1", "type": "text",
            "room": "My Room", "from": "Alice", "body": "hello",
        }))
        self.assertEqual(EventKind.TEXT, event.kind)
        self.assertEqual("My Room", event.room)
        self.assertEqual("alice", event.user_key)

    def test_login_image_and_join_events_are_normalized(self):
        decoder = EventDecoder()
        login = decoder.decode('{"handler":"login_event","type":"success"}')
        image = decoder.decode('{"handler":"room_event","type":"image","room":"R","from":"A","url":"u"}')
        joined = decoder.decode('{"handler":"room_event","type":"user_joined","name":"R","username":"A"}')
        self.assertEqual(EventKind.LOGIN_SUCCESS, login.kind)
        self.assertEqual(EventKind.IMAGE, image.kind)
        self.assertEqual(EventKind.USER_JOINED, joined.kind)

    def test_malformed_unknown_and_duplicate_events_are_safe(self):
        decoder = EventDecoder()
        self.assertEqual(EventKind.MALFORMED, decoder.decode("not json").kind)
        self.assertEqual(EventKind.UNKNOWN, decoder.decode('{"handler":"new_event"}').kind)
        payload = '{"handler":"room_event","id":"same","type":"text","room":"R","from":"A","body":"x"}'
        self.assertEqual(EventKind.TEXT, decoder.decode(payload).kind)
        self.assertEqual(EventKind.DUPLICATE, decoder.decode(payload).kind)

    def test_bytes_and_missing_fields_do_not_raise(self):
        decoder = EventDecoder()
        self.assertEqual(EventKind.TEXT, decoder.decode(b'{"handler":"room_event","type":"text"}').kind)
        self.assertEqual(EventKind.MALFORMED, decoder.decode(b'\xff').kind)
        self.assertEqual("strasse", normalize_identity("  Straße "))


if __name__ == "__main__":
    unittest.main()
