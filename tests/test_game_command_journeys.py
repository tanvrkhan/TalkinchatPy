import asyncio
import unittest

import commands  # noqa: F401
from registry import DispatchContext, REGISTRY
from command_modules.cards import _format_hand


class FakeCards:
    def __init__(self):
        self.played = None

    async def private_hand(self, room, user, user_key, **kwargs):
        self.hand_page = kwargs.get("page", 1)
        return {
            "game": "uno", "page": 1, "pages": 1,
            "cards": [{"id": "c1", "color": "red", "value": "7"}],
            "buttons": [
                {"label": "Red 7", "message": ",playcard card_7_token"},
                {"label": "Draw", "message": ",drawcard 7"},
                {"label": "UNO!", "message": ",calluno 7"},
            ],
            "version": 7,
        }

    async def play(self, room, user, user_key, action_id):
        self.played = action_id
        return {"kind": "played", "room": room, "action": action_id}

    async def draw(self, room, user, user_key, expected_version=None):
        return {"kind": "drawn", "version": expected_version}

    async def call_uno(self, room, user, user_key, expected_version=None):
        return {"kind": "uno_called", "version": expected_version}


class FakeCricket:
    def __init__(self):
        self.delivery = None
        self.bet = None

    def match_for_room(self, room):
        return {
            "match_id": "m1", "revision": 7,
            "innings": {"batting": "a", "bowling": "b", "striker": "alice", "bowler": "bob"},
            "teams": {
                "a": {"players": [{"key": "alice"}]},
                "b": {"players": [{"key": "bob"}]},
            },
        }

    def match_for_player(self, player):
        return self.match_for_room("Room")

    async def toss_choice(self, match, user, decision):
        self.toss = (match, user, decision)
        return {"kind": "toss", "decision": decision}

    async def start(self, room, solo=False):
        self.started = (room, solo)
        return {"kind": "paired", "match": {}}

    async def add_ai(self, room, user, user_key):
        self.ai = (room, user, user_key)
        return {"kind": "ai_added"}

    async def leave(self, room, user, user_key):
        self.left = (room, user, user_key)
        return {"kind": "left"}

    async def cancel(self, room, player_key=None, is_admin=False):
        self.cancelled = (room, player_key, is_admin)
        return {"kind": "cancelled"}

    async def proxy_choice(self, match, user, side, number, revision):
        self.proxy = (match, user, side, number, revision)
        return {"kind": "proxy"}

    async def delivery_choice(self, match, user, side, number, revision):
        self.delivery = (match, user, side, number, revision)
        return {"kind": "delivery"}

    async def place_bet(self, match, user, user_key, team, amount):
        self.bet = (match, user, user_key, team, amount)
        return {"kind": "bet"}


class Bot:
    def __init__(self):
        self.card_sessions = FakeCards()
        self.cricket = FakeCricket()
        self.replies = []

    async def reply(self, context, text):
        self.replies.append(str(text))


class Transport:
    def __init__(self, bot):
        self.bot = bot

    async def send_dm(self, user, text):
        self.bot.replies.append(str(text))


class GameCommandJourneyTests(unittest.TestCase):
    def test_card_play_and_draw_reach_session_manager(self):
        bot = Bot()
        context = DispatchContext("Alice", "Room")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",playcard action-1")))
        self.assertIn("played", bot.replies[-1])
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",drawcard 8")))
        self.assertIn("drawn", bot.replies[-1])

    def test_private_hand_lists_working_numbered_text_commands(self):
        bot = Bot()
        bot.transport = Transport(bot)
        context = DispatchContext("Alice", "")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",hand")))
        self.assertIn(",playcard 1", bot.replies[-1])
        self.assertIn(",drawcard 7", bot.replies[-1])
        self.assertIn(",calluno 7", bot.replies[-1])

        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",playcard 1")))
        self.assertEqual("card_7_token", bot.card_sessions.played)

        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",hand 2")))
        self.assertEqual(2, bot.card_sessions.hand_page)

    def test_later_hand_pages_encode_page_in_card_command(self):
        text = _format_hand({
            "game": "uno", "page": 2, "pages": 3,
            "buttons": [{"label": "Blue 4", "message": ",playcard card_8_token"}],
        })
        self.assertIn(",playcard 2.1", text)

    def test_uno_text_action_and_cricket_dm_toss_are_reachable(self):
        bot = Bot()
        context = DispatchContext("Alice", "")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",calluno 7")))
        self.assertIn("uno_called", bot.replies[-1])
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",crickettoss bat")))
        self.assertEqual(("m1", "alice", "bat"), bot.cricket.toss)

    def test_all_player_cricket_actions_have_text_commands(self):
        bot = Bot()
        room = DispatchContext("Alice", "Room")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, room, ",cricketai")))
        self.assertEqual(("Room", "Alice", "alice"), bot.cricket.ai)

    def test_cricket_has_explicit_solo_and_queue_commands(self):
        bot = Bot()
        room = DispatchContext("Alice", "Room")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, room, ",cricketsolo")))
        self.assertEqual(("Room", True), bot.cricket.started)
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, room, ",cricketqueue")))
        self.assertEqual(("Room", False), bot.cricket.started)
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, room, ",cricketproxy bowl 3")))
        self.assertEqual(("m1", "alice", "bowl", 3, 7), bot.cricket.proxy)
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, room, ",cricketleave")))
        self.assertEqual(("Room", "Alice", "alice"), bot.cricket.left)
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, room, ",cricketend")))
        self.assertEqual(("Room", "alice", False), bot.cricket.cancelled)

    def test_numbered_cricket_alias_submits_real_delivery(self):
        bot = Bot()
        context = DispatchContext("Alice", "Room")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",b4")))
        self.assertEqual(("m1", "alice", "bat", 4, 7), bot.cricket.delivery)

    def test_cricket_bet_reaches_atomic_manager(self):
        bot = Bot()
        context = DispatchContext("Alice", "Room")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",cricketbet a 500")))
        self.assertEqual(("m1", "Alice", "alice", "a", 500), bot.cricket.bet)


if __name__ == "__main__":
    unittest.main()
