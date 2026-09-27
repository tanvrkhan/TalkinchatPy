import asyncio
import tempfile
import unittest
from pathlib import Path

from bot import TalkinChatBot
from config import Config
from registry import DispatchContext


class PrivilegedDispatchTests(unittest.TestCase):
    def make_bot(self, root):
        config = Config.from_env({
            "TALKINCHAT_USERNAME": "owner",
            "TALKINCHAT_PASSWORD": "secret",
            "TALKINCHAT_ROOM": "Room",
            "TALKINCHAT_STATE_DIR": root,
        })
        bot = TalkinChatBot(config)
        bot.replies = []

        async def reply(context, text):
            bot.replies.append(str(text))

        bot.reply = reply
        return bot

    def test_ordinary_user_cannot_mutate_moderation_state_and_rejection_is_audited(self):
        with tempfile.TemporaryDirectory() as root:
            bot = self.make_bot(root)
            context = DispatchContext("ordinary", "Room", "user")
            handled = asyncio.run(bot.dispatch(context, ",warn Alice"))
            self.assertTrue(handled)
            self.assertEqual({}, bot.store.get("warnings", {}))
            self.assertIn("permission", bot.replies[-1].lower())
            actions = bot.activity.admin_log("Room").entries
            self.assertEqual("rejected", actions[0].outcome)
            self.assertEqual("warn", actions[0].action)
            self.assertNotIn("Alice", actions[0].detail)

    def test_room_authority_is_scoped_and_success_is_audited(self):
        with tempfile.TemporaryDirectory() as root:
            bot = self.make_bot(root)
            bot.store.set("room_authorities", {"room": ["local-mod"]})
            bot.refresh_access()
            allowed = DispatchContext("LOCAL-MOD", "Room", "user")
            denied = DispatchContext("LOCAL-MOD", "Other", "user")
            self.assertTrue(asyncio.run(bot.dispatch(allowed, ",warn Alice")))
            self.assertEqual(1, bot.store.get("warnings")["room"]["alice"])
            self.assertTrue(asyncio.run(bot.dispatch(denied, ",warn Alice")))
            self.assertNotIn("other", bot.store.get("warnings"))
            actions = bot.activity.admin_log("Room").entries
            self.assertEqual("success", actions[0].outcome)


if __name__ == "__main__":
    unittest.main()
