import asyncio
import tempfile
import unittest
from pathlib import Path

import commands  # noqa: F401
from config_store import ConfigStore
from registry import DispatchContext, REGISTRY
from services import slap


class Bot:
    def __init__(self, root):
        self.store = ConfigStore(Path(root))
        self.replies = []

    async def reply(self, context, text):
        self.replies.append(str(text))


class ExtendedCommandTests(unittest.TestCase):
    def test_new_user_profile_and_liked_are_safe(self):
        with tempfile.TemporaryDirectory() as root:
            old = slap.DATA_FILE
            slap.DATA_FILE = str(Path(root) / "slap.json")
            slap._data = {}
            try:
                bot = Bot(root)
                context = DispatchContext("New User", "Room")
                self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",profile")))
                self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",liked")))
                self.assertIn("Reputation", bot.replies[-1])
            finally:
                slap.DATA_FILE = old


if __name__ == "__main__":
    unittest.main()
