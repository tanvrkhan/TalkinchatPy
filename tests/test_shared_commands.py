import asyncio
import unittest
from unittest.mock import patch

import commands  # noqa: F401
from registry import DispatchContext, REGISTRY


class Bot:
    def __init__(self):
        self.replies = []

    async def reply(self, context, text):
        self.replies.append(text)


class SharedCommandTests(unittest.TestCase):
    def test_calculator_uses_safe_service(self):
        bot = Bot()
        handled = asyncio.run(REGISTRY.dispatch(
            bot, DispatchContext("Alice", "Room"), ",calc 2*(3+4)"))
        self.assertTrue(handled)
        self.assertEqual(["2*(3+4) = 14"], bot.replies)

    def test_ai_command_uses_normalized_user_key(self):
        bot = Bot()
        with patch("command_modules.fun_ai.ai.ask", return_value="hello") as ask:
            asyncio.run(REGISTRY.dispatch(
                bot, DispatchContext(" Straße ", "Room"), "!askai hi"))
        ask.assert_called_once_with("strasse", "hi")
        self.assertEqual(["hello"], bot.replies)


if __name__ == "__main__":
    unittest.main()
