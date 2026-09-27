import copy
import json
import random
import unittest

from services.cards import card_to_dict, standard_deck
from services.thulla import auto_play, legal_card_ids, new_game, play, public_view


CARDS = {(card.suit, card.rank): card_to_dict(card) for card in standard_deck()}


def card(suit, rank):
    return copy.deepcopy(CARDS[(suit, rank)])


def card_id(suit, rank):
    return CARDS[(suit, rank)]["id"]


def state_with_hands(hands, current_player, *, first_trick=False, waste=None):
    players = list(hands)
    return {
        "game": "thulla",
        "phase": "playing",
        "players": players,
        "hands": {
            player: [card(suit, rank) for suit, rank in player_cards]
            for player, player_cards in hands.items()
        },
        "current_player": current_player,
        "trick": [],
        "first_trick": first_trick,
        "waste": [card(suit, rank) for suit, rank in (waste or [])],
        "waste_order": [item["id"] for item in map(card_to_dict, standard_deck())],
        "safe_players": [],
        "loser": None,
    }


class ThullaRulesTests(unittest.TestCase):
    def test_new_game_accepts_two_through_eight_unique_players(self):
        for count in (2, 8):
            with self.subTest(count=count):
                players = [f"p{index}" for index in range(count)]
                state = new_game(players, random.Random(17))
                self.assertEqual(players, state["players"])

        for players in (("alice",), tuple(f"p{index}" for index in range(9))):
            with self.subTest(players=len(players)):
                with self.assertRaises(ValueError):
                    new_game(list(players), random.Random(17))

        with self.assertRaises(ValueError):
            new_game(["alice", "alice"], random.Random(17))

    def test_new_game_deals_evenly_and_ace_of_spades_must_open(self):
        state = new_game(
            ["alice", "bob", "cara", "dan", "eve"], random.Random(23)
        )

        counts = [len(state["hands"][player]) for player in state["players"]]
        self.assertEqual(52, sum(counts))
        self.assertLessEqual(max(counts) - min(counts), 1)
        opener = state["current_player"]
        self.assertIn(card_id("spades", "A"), legal_card_ids(state, opener))
        self.assertEqual({card_id("spades", "A")}, legal_card_ids(state, opener))
        json.dumps(state, allow_nan=False)

    def test_first_trick_allows_off_suit_and_is_always_discarded(self):
        state = state_with_hands(
            {
                "alice": [("spades", "A"), ("hearts", "2")],
                "bob": [("spades", "2"), ("hearts", "3")],
                "cara": [("clubs", "2"), ("hearts", "4")],
            },
            "alice",
            first_trick=True,
        )

        play(state, "alice", card_id("spades", "A"))
        play(state, "bob", card_id("spades", "2"))
        self.assertEqual({card_id("clubs", "2"), card_id("hearts", "4")},
                         legal_card_ids(state, "cara"))
        event = play(state, "cara", card_id("clubs", "2"))

        self.assertEqual("discard", event["kind"])
        self.assertEqual("alice", event["leader"])
        self.assertEqual("alice", state["current_player"])
        self.assertFalse(state["first_trick"])
        self.assertEqual([], state["trick"])
        self.assertEqual(3, len(state["waste"]))

    def test_later_tricks_require_following_the_led_suit(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "10"), ("spades", "2")],
                "bob": [("hearts", "K"), ("clubs", "2")],
                "cara": [("diamonds", "3")],
            },
            "alice",
        )

        play(state, "alice", card_id("hearts", "10"))

        self.assertEqual({card_id("hearts", "K")}, legal_card_ids(state, "bob"))

    def test_first_off_suit_card_ends_trick_and_highest_led_suit_picks_up(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "10"), ("spades", "2")],
                "bob": [("hearts", "K")],
                "cara": [("clubs", "2"), ("diamonds", "3")],
                "dan": [("hearts", "A"), ("spades", "3")],
            },
            "alice",
        )

        play(state, "alice", card_id("hearts", "10"))
        play(state, "bob", card_id("hearts", "K"))
        event = play(state, "cara", card_id("clubs", "2"))

        self.assertEqual("thulla", event["kind"])
        self.assertEqual("bob", event["collector"])
        self.assertEqual("bob", state["current_player"])
        self.assertEqual(3, len(state["hands"]["bob"]))
        self.assertEqual([], state["trick"])
        self.assertEqual([], state["waste"])
        self.assertEqual(
            [card_id("hearts", "A"), card_id("spades", "3")],
            [item["id"] for item in state["hands"]["dan"]],
        )
        self.assertNotIn("dan", [entry["player"] for entry in event["cards"]])

    def test_all_following_discards_trick_and_high_card_leads(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "10"), ("spades", "2")],
                "bob": [("hearts", "K"), ("clubs", "2")],
                "cara": [("hearts", "3"), ("diamonds", "3")],
            },
            "alice",
        )

        play(state, "alice", card_id("hearts", "10"))
        play(state, "bob", card_id("hearts", "K"))
        event = play(state, "cara", card_id("hearts", "3"))

        self.assertEqual("discard", event["kind"])
        self.assertEqual("bob", event["leader"])
        self.assertEqual("bob", state["current_player"])
        self.assertEqual(3, len(state["waste"]))
        self.assertEqual(1, len(state["hands"]["bob"]))

    def test_empty_high_card_draws_from_prior_waste_before_discarding_trick(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "2"), ("spades", "3")],
                "bob": [("hearts", "3"), ("clubs", "3")],
                "cara": [("hearts", "K")],
            },
            "alice",
            waste=[("clubs", "2"), ("diamonds", "2"), ("spades", "2")],
        )

        play(state, "alice", card_id("hearts", "2"))
        play(state, "bob", card_id("hearts", "3"))
        event = play(state, "cara", card_id("hearts", "K"))

        self.assertEqual("discard", event["kind"])
        self.assertEqual("cara", state["current_player"])
        self.assertEqual([card_id("clubs", "2")],
                         [item["id"] for item in state["hands"]["cara"]])
        self.assertEqual(5, len(state["waste"]))
        self.assertNotIn(card_id("clubs", "2"), json.dumps(event))

    def test_empty_non_leader_is_safe_and_last_player_with_cards_loses(self):
        state = state_with_hands(
            {"alice": [("hearts", "2")], "bob": [("clubs", "2")]},
            "alice",
        )

        play(state, "alice", card_id("hearts", "2"))
        event = play(state, "bob", card_id("clubs", "2"))

        self.assertEqual("thulla", event["kind"])
        self.assertTrue(event["finished"])
        self.assertEqual("alice", state["loser"])
        self.assertEqual(["bob"], state["safe_players"])
        self.assertEqual("finished", state["phase"])
        self.assertIsNone(state["current_player"])

    def test_two_player_final_lead_loses_immediately_when_opponent_thullas(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "2")],
                "bob": [("clubs", "2"), ("diamonds", "3")],
            },
            "alice",
        )

        play(state, "alice", card_id("hearts", "2"))
        event = play(state, "bob", card_id("clubs", "2"))

        self.assertEqual("thulla", event["kind"])
        self.assertTrue(event["finished"])
        self.assertEqual("alice", state["loser"])
        self.assertEqual(["bob"], state["safe_players"])
        self.assertEqual([], state["hands"]["alice"])
        self.assertEqual(
            [card_id("diamonds", "3")],
            [item["id"] for item in state["hands"]["bob"]],
        )
        self.assertEqual(
            [card_id("hearts", "2"), card_id("clubs", "2")],
            [item["id"] for item in state["waste"]],
        )
        self.assertIsNone(state["current_player"])

    def test_all_empty_all_follow_ends_without_drawing_from_prior_waste(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "K")],
                "bob": [("hearts", "2")],
            },
            "alice",
            waste=[("clubs", "2"), ("diamonds", "2")],
        )
        prior_waste = copy.deepcopy(state["waste"])

        play(state, "alice", card_id("hearts", "K"))
        event = play(state, "bob", card_id("hearts", "2"))

        self.assertEqual("discard", event["kind"])
        self.assertFalse(event["forced_draw"])
        self.assertTrue(event["finished"])
        self.assertEqual("alice", state["loser"])
        self.assertEqual(["bob"], state["safe_players"])
        self.assertEqual([], state["hands"]["alice"])
        self.assertEqual([], state["hands"]["bob"])
        self.assertEqual(prior_waste, state["waste"][: len(prior_waste)])
        self.assertEqual(4, len(state["waste"]))
        self.assertIsNone(state["current_player"])

    def test_rejected_plays_do_not_mutate_state(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "10"), ("spades", "2")],
                "bob": [("hearts", "K"), ("clubs", "2")],
                "cara": [("diamonds", "3")],
            },
            "alice",
        )
        play(state, "alice", card_id("hearts", "10"))

        rejected = (
            ("cara", card_id("diamonds", "3")),
            ("bob", card_id("clubs", "2")),
            ("bob", card_id("diamonds", "A")),
        )
        for user, played_card_id in rejected:
            with self.subTest(user=user, card_id=played_card_id):
                before = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    play(state, user, played_card_id)
                self.assertEqual(before, state)

    def test_auto_play_uses_lowest_ranked_legal_card(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "10"), ("spades", "2")],
                "bob": [("hearts", "K"), ("hearts", "2"), ("clubs", "2")],
                "cara": [("diamonds", "3")],
            },
            "alice",
        )
        play(state, "alice", card_id("hearts", "10"))

        event = auto_play(state, "bob")

        self.assertEqual(card_id("hearts", "2"), event["card"]["id"])
        self.assertTrue(event["automatic"])
        self.assertNotIn(card_id("hearts", "2"),
                         [item["id"] for item in state["hands"]["bob"]])

    def test_public_view_hides_hands_waste_and_draw_order(self):
        state = state_with_hands(
            {
                "alice": [("hearts", "10"), ("spades", "2")],
                "bob": [("hearts", "K"), ("clubs", "2")],
            },
            "alice",
            waste=[("diamonds", "2")],
        )
        play(state, "alice", card_id("hearts", "10"))

        view = public_view(state)

        self.assertNotIn("hands", view)
        self.assertNotIn("waste", view)
        self.assertNotIn("waste_order", view)
        self.assertEqual({"alice": 1, "bob": 2}, view["card_counts"])
        self.assertEqual(card_id("hearts", "10"), view["trick"][0]["card"]["id"])
        json.dumps(view, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
