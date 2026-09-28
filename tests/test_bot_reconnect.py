import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from websockets.exceptions import WebSocketException

from bot import TalkinChatBot
from config import Config
from transports.talkinchat import Event, EventKind, protobuf_fields


class ClosingSocket:
    def __init__(self, frames):
        self.frames = frames
        self.sent = []

    async def send(self, frame):
        self.sent.append(frame)

    def __aiter__(self):
        self.iterator = iter(self.frames)
        return self

    async def __anext__(self):
        try:
            value = next(self.iterator)
        except StopIteration:
            raise ConnectionError("closed")
        return value


class ReconnectTests(unittest.TestCase):
    def config(self):
        return Config.from_env({
            "TALKINCHAT_USERNAME": "bot", "TALKINCHAT_PASSWORD": "pw",
            "TALKINCHAT_ROOM": "Room One,Room Two",
            "TALKINCHAT_STATE_DIR": "/tmp/talkinchat-bot-tests",
            "TALKINCHAT_WEBSOCKET_URL": "wss://example.invalid/server",
        })

    def test_login_success_joins_all_rooms_and_ignores_bad_frames(self):
        socket = ClosingSocket([
            "bad", '{"handler":"new"}',
            '{"handler":"login_event","type":"success"}',
        ])
        bot = TalkinChatBot(self.config(), connector=lambda _: socket)
        with self.assertRaises(ConnectionError):
            asyncio.run(bot.run_connection())
        payloads = [protobuf_fields(item) for item in socket.sent]
        self.assertEqual(
            ["Room One", "Room Two"],
            [item[6][0].decode() for item in payloads],
        )
        self.assertTrue((self.config().state_dir / "ready.json").is_file())

    def test_incoming_dm_dispatches_with_private_context(self):
        socket = ClosingSocket([
            '{"handler":"login_event","type":"success"}',
            '{"handler":"chat_message","type":"text","from":"Alice",'
            '"to":"bot","body":",help"}',
        ])
        registry = Mock()
        registry.parse.return_value = ("help", "")
        registry.get.return_value = SimpleNamespace(
            name="help", level="user", room_admin=False)
        registry.dispatch = AsyncMock(return_value=True)
        bot = TalkinChatBot(
            self.config(), connector=lambda _: socket, registry=registry)
        with self.assertRaises(ConnectionError):
            asyncio.run(bot.run_connection())
        context = registry.dispatch.await_args.args[1]
        self.assertTrue(context.is_dm)
        self.assertEqual("Alice", context.user)

    def test_reconnect_uses_bounded_backoff(self):
        attempts = []
        sleeps = []

        async def connector(_):
            attempts.append(1)
            raise ConnectionError("offline")

        async def sleep(delay):
            sleeps.append(delay)
            if len(sleeps) == 4:
                raise asyncio.CancelledError

        bot = TalkinChatBot(self.config(), connector=connector, sleep=sleep)
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(bot.run_forever())
        self.assertEqual([1.0, 2.0, 4.0, 8.0], sleeps)

    def test_protocol_errors_use_the_same_bounded_reconnect_path(self):
        sleeps = []

        async def connector(_):
            raise WebSocketException("protocol closed")

        async def sleep(delay):
            sleeps.append(delay)
            raise asyncio.CancelledError

        bot = TalkinChatBot(self.config(), connector=connector, sleep=sleep)
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(bot.run_forever())
        self.assertEqual([1.0], sleeps)

    def test_membership_watchdog_renews_every_configured_room(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)
            if len(sleeps) > 1:
                raise asyncio.CancelledError

        bot = TalkinChatBot(self.config(), sleep=sleep)
        bot.transport = AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(bot.maintain_room_membership())
        self.assertEqual([60.0, 60.0], sleeps)
        self.assertEqual(
            [unittest.mock.call("Room One"), unittest.mock.call("Room Two")],
            bot.transport.join_room.await_args_list,
        )

    def test_membership_watchdog_closes_socket_when_renewal_fails(self):
        async def sleep(_delay):
            return None

        bot = TalkinChatBot(self.config(), sleep=sleep)
        bot.transport = AsyncMock()
        bot.transport.join_room = AsyncMock(side_effect=ConnectionError("closed"))
        with self.assertRaises(ConnectionError):
            asyncio.run(bot.maintain_room_membership())
        bot.transport.websocket.close.assert_awaited_once_with()

    def test_initialize_restores_card_sessions_once(self):
        bot = TalkinChatBot(self.config())
        bot.card_sessions.restore = AsyncMock()
        asyncio.run(bot.initialize())
        asyncio.run(bot.initialize())
        bot.card_sessions.restore.assert_awaited_once_with()

    def test_censorkick_applies_only_to_enabled_non_exempt_public_users(self):
        bot = TalkinChatBot(self.config())
        bot.transport = AsyncMock()
        bot.store.set("censor_words", {"room one": ["badword"]})
        bot.store.set("censorkick_rooms", {"room one": True})
        bot.store.set("censor_exempt", {})
        event = Event(
            EventKind.TEXT, room="Room One", user="Alice", user_key="alice",
            body="contains badword",
        )
        self.assertTrue(asyncio.run(bot.apply_censor_policy(event)))
        bot.transport.kick.assert_awaited_once_with("Room One", "Alice")

        bot.transport.kick.reset_mock()
        bot.store.set("censor_exempt", {"room one": ["alice"]})
        self.assertFalse(asyncio.run(bot.apply_censor_policy(event)))
        bot.transport.kick.assert_not_awaited()

        bot.store.set("censor_exempt", {})
        bot.access.level_of = Mock(return_value="admin")
        self.assertFalse(asyncio.run(bot.apply_censor_policy(event)))
        bot.transport.kick.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
