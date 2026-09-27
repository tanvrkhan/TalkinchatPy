import unittest

from transports.talkinchat import (
    AuthResult,
    EventDecoder,
    EventKind,
    build_auth_request,
    authenticate,
    message_payload,
    parse_auth_result,
    protobuf_fields,
    room_payload,
    websocket_headers,
)


def field(number, value):
    data = value.encode() if isinstance(value, str) else value
    tag = (number << 3) | 2
    encoded = bytearray()
    for value_part in (tag, len(data)):
        while value_part > 127:
            encoded.append((value_part & 127) | 128)
            value_part >>= 7
        encoded.append(value_part)
    return bytes(encoded) + data


class CurrentProtocolTests(unittest.TestCase):
    def test_auth_request_matches_v583_field_contract(self):
        payload = build_auth_request(
            "Bot", "secret", sid="sid", device_id="device", device_model="model",
        )
        fields = protobuf_fields(payload)
        self.assertEqual(b"login", fields[1][0])
        self.assertEqual(b"Bot", fields[2][0])
        self.assertEqual(b"secret", fields[3][0])
        self.assertEqual(b"444", fields[9][0])
        self.assertEqual(b"2", fields[10][0])
        self.assertEqual(b"device", fields[11][0])
        self.assertEqual(b"model", fields[12][0])
        self.assertEqual(b"1", fields[14][0])

    def test_auth_result_extracts_server_and_method(self):
        payload = field(1, "ok") + field(2, "91") + field(5, "captcha") + field(7, "5443") + field(8, "1")
        self.assertEqual(
            AuthResult("ok", "91", "captcha", "", "5443", "1", ""),
            parse_auth_result(payload),
        )

    def test_authentication_posts_binary_and_rejects_server_errors(self):
        class Response:
            content = field(1, "ok") + field(7, "5443") + field(8, "1")

            def raise_for_status(self):
                pass

        class Session:
            def post(self, url, **kwargs):
                self.url, self.kwargs = url, kwargs
                return Response()

        session = Session()
        result = authenticate("https://chatp.net/api?auth_new", "Bot", "pw",
                              device_id="device", session=session)
        self.assertEqual("5443", result.server)
        self.assertEqual("application/octet-stream", session.kwargs["headers"]["Content-Type"])

    def test_current_query_payloads_are_binary_protobuf(self):
        join = protobuf_fields(room_payload("room_join", "My Room", "ignored"))
        self.assertEqual(b"room_join", join[1][0])
        self.assertEqual(b"My Room", join[6][0])
        self.assertEqual(b"", join[9][0])
        self.assertEqual(0, join[13][0])

        message = protobuf_fields(message_payload(
            "room_message", "My Room", "text", "ignored", body="hello"))
        self.assertEqual(b"room_message", message[1][0])
        self.assertEqual(b"text", message[2][0])
        self.assertEqual(b"hello", message[5][0])
        self.assertEqual(b"My Room", message[6][0])

    def test_binary_result_message_decodes_room_text_and_login(self):
        room_event = field(1, "text") + field(2, "Alice") + field(6, "hello") + field(13, "Lobby") + field(14, "42") + field(41, "event-1")
        frame = bytes([8, 6]) + field(10, room_event)
        event = EventDecoder().decode(frame)
        self.assertEqual(EventKind.TEXT, event.kind)
        self.assertEqual("Lobby", event.room)
        self.assertEqual("Alice", event.user)
        self.assertEqual("hello", event.body)
        self.assertEqual("event-1", event.event_id)

        self.assertEqual(EventKind.LOGIN_SUCCESS, EventDecoder().decode(bytes([8, 16])).kind)

    def test_binary_result_message_decodes_incoming_dm_only(self):
        message = (
            field(1, "text") + field(2, "dm-1") + field(3, "Alice")
            + field(4, "Bot") + field(5, ",help")
        )
        incoming = bytes([8, 12]) + field(9, message)
        event = EventDecoder().decode(incoming)
        self.assertEqual(EventKind.DIRECT_TEXT, event.kind)
        self.assertEqual("", event.room)
        self.assertEqual("Alice", event.user)
        self.assertEqual(",help", event.body)
        self.assertEqual("dm-1", event.event_id)

        sent_echo = bytes([8, 13]) + field(9, message)
        self.assertEqual(EventKind.UNKNOWN, EventDecoder().decode(sent_echo).kind)

    def test_token_authentication_uses_the_verified_b_header(self):
        auth = AuthResult("ok", "91", "captcha", "", "5443", "n", "photo")
        headers = websocket_headers("Bot", "pw", auth, device_id="device", device_model="model")
        self.assertEqual({"b"}, set(headers))


if __name__ == "__main__":
    unittest.main()
