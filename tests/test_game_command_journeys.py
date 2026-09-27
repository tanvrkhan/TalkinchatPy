import asyncio
import unittest

import commands  # noqa: F401
from registry import DispatchContext, REGISTRY


class FakeCards:
    async def play(self, room, user, user_key, action_id):
        return {"kind": "played", "room": room, "action": action_id}

    async def draw(self, room, user, user_key, expected_version=None):
        return {"kind": "drawn", "version": expected_version}


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


class GameCommandJourneyTests(unittest.TestCase):
    def test_card_play_and_draw_reach_session_manager(self):
        bot = Bot()
        context = DispatchContext("Alice", "Room")
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",playcard action-1")))
        self.assertIn("played", bot.replies[-1])
        self.assertTrue(asyncio.run(REGISTRY.dispatch(bot, context, ",drawcard 8")))
        self.assertIn("drawn", bot.replies[-1])

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
