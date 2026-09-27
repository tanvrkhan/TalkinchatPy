import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import commands  # noqa: F401
from command_modules.meta import HELP_MESSAGE_LIMIT
from registry import DispatchContext, REGISTRY
from config_store import ConfigStore


class Bot:
    def __init__(self, root):
        self.replies = []
        self.store = ConfigStore(Path(root))

    async def reply(self, context, text):
        self.replies.append(str(text))


class HelpSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_default_help_is_compact_and_points_to_categories(self):
        bot = Bot(self.temp.name)
        asyncio.run(REGISTRY.dispatch(bot, DispatchContext("Alice", "Room"), ",help"))
        self.assertLessEqual(len(bot.replies[-1]), HELP_MESSAGE_LIMIT)
        self.assertIn(",help games", bot.replies[-1].casefold())

    def test_category_help_is_paginated_below_protocol_limit(self):
        bot = Bot(self.temp.name)
        asyncio.run(REGISTRY.dispatch(bot, DispatchContext("Alice", "Room"), ",help games 1"))
        self.assertLessEqual(len(bot.replies[-1]), HELP_MESSAGE_LIMIT)
        self.assertIn("games", bot.replies[-1].casefold())

    def test_slap_command_reports_immediate_bot_round_without_raised_state(self):
        bot = Bot(self.temp.name)
        result = {
            "action": "fight", "winner": {"name": "Alice"},
            "loser": {"name": "TalkinChat Bot", "health": 50},
            "gained": 1000, "lost": 0, "critical": True,
        }
        with mock.patch("command_modules.extended.slap.slap", return_value=result):
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("Alice", "Room"), ",slap"))
        self.assertIn("Alice slapped TalkinChat Bot", bot.replies[-1])
        self.assertNotIn("raised", bot.replies[-1].casefold())


if __name__ == "__main__":
    unittest.main()
