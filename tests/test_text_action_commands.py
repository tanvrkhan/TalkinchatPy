import asyncio
import tempfile
import unittest
from pathlib import Path

import commands  # noqa: F401
from config_store import ConfigStore
from registry import DispatchContext, REGISTRY


class Bot:
    def __init__(self, root):
        self.store = ConfigStore(Path(root))
        self.replies = []

    async def reply(self, context, text):
        self.replies.append(str(text))


class TextActionCommandTests(unittest.TestCase):
    def test_poll_advertises_vote_command_and_records_one_vote_per_user(self):
        with tempfile.TemporaryDirectory() as root:
            bot = Bot(root)
            context = DispatchContext("Alice", "Room")
            asyncio.run(REGISTRY.dispatch(bot, context, ",poll Lunch? | Pizza | Curry"))
            self.assertIn(",vote 1", bot.replies[-1])
            asyncio.run(REGISTRY.dispatch(bot, context, ",vote 2"))
            self.assertIn("Curry", bot.replies[-1])
            poll = bot.store.get("polls", {})["room"]
            self.assertEqual(2, poll["votes"]["alice"])


if __name__ == "__main__":
    unittest.main()
