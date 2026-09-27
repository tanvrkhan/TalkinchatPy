import asyncio
import tempfile
import unittest
from pathlib import Path

import commands  # noqa: F401
from config_store import ConfigStore
from registry import DispatchContext, REGISTRY
from transports.talkinchat import OperationResult


class Transport:
    def __init__(self):
        self.joined = []

    async def join_room(self, room):
        self.joined.append(room)

    async def kick(self, room, user):
        return OperationResult(False, "Kick is not supported by the verified TalkinChat protocol.")


class Bot:
    def __init__(self, root):
        self.transport = Transport()
        self.store = ConfigStore(root)
        self.replies = []

    async def reply(self, context, text):
        self.replies.append(text)


class RoomCommandTests(unittest.TestCase):
    def test_join_preserves_room_spelling(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("owner", "", "admin"), ",join My Room"))
            self.assertEqual(["My Room"], bot.transport.joined)

    def test_unsupported_kick_reports_fallback_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(Path(root))
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("owner", "My Room", "admin"), ",kick Alice"))
            self.assertIn("not supported", bot.replies[-1])


if __name__ == "__main__":
    unittest.main()
