import asyncio
import unittest

from bot import TalkinChatBot
from config import Config


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
        })

    def test_login_success_joins_all_rooms_and_ignores_bad_frames(self):
        socket = ClosingSocket([
            "bad", '{"handler":"new"}',
            '{"handler":"login_event","type":"success"}',
        ])
        bot = TalkinChatBot(self.config(), connector=lambda _: socket)
        with self.assertRaises(ConnectionError):
            asyncio.run(bot.run_connection())
        payloads = [__import__("json").loads(item) for item in socket.sent]
        self.assertEqual("login", payloads[0]["handler"])
        self.assertEqual(["Room One", "Room Two"], [item["name"] for item in payloads[1:]])

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


if __name__ == "__main__":
    unittest.main()
