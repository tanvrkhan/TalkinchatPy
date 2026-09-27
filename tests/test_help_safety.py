import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_slap_command_reports_cross_room_fight(self):
        bot = Bot(self.temp.name)
        result = {
            "action": "fight", "winner": {"name": "Alice", "room": "Room A", "xp": 11000},
            "loser": {"name": "Bob", "room": "Room B", "health": 50, "xp": 9000},
            "gained": 1000, "lost": 0, "critical": True,
            "damage": 50, "blocked": False, "streak": 1,
        }
        bot.transport = mock.AsyncMock()
        with mock.patch("command_modules.extended.slap.slap", return_value=result):
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("Alice", "Room"), ",slap"))
        messages = [call.args[1] for call in bot.transport.say.await_args_list]
        self.assertEqual(2, len(messages))
        self.assertIn("Alice", messages[0])
        self.assertIn("Bob", messages[0])

    def test_raised_slap_hand_is_announced_to_all_configured_rooms(self):
        bot = Bot(self.temp.name)
        bot.config = SimpleNamespace(rooms=("Room A", "Room B"))
        bot.transport = mock.AsyncMock()
        with mock.patch(
            "command_modules.extended.slap.slap",
            return_value={"action": "raised", "room": "Room A", "avatar": ""},
        ):
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext("Alice", "Room A"), ",slap"))
        self.assertEqual(
            [mock.call("Room A", mock.ANY), mock.call("Room B", mock.ANY)],
            bot.transport.say.await_args_list,
        )


if __name__ == "__main__":
    unittest.main()
