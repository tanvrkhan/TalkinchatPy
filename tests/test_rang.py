import copy
import json
import random
import unittest

from services.cards import card_to_dict, standard_deck
from services.rang import (
    auto_play,
    choose_trump,
    legal_card_ids,
    new_game,
    play,
    public_view,
    resume,
)


PLAYERS = ["alice", "bob", "cara", "dan"]
CARDS = {(card.suit, card.rank): card_to_dict(card) for card in standard_deck()}


def card(suit, rank):
    return copy.deepcopy(CARDS[(suit, rank)])


def card_id(suit, rank):
    return CARDS[(suit, rank)]["id"]


def playing_state(
    hands,
    current_player,
    *,
    trick=None,
    trump="spades",
    dealer="bob",
    team_tricks=(0, 0),
    deal_streaks=(0, 0),
    courts=(0, 0),
    court_target=2,
    timeout_counts=None,
):
    full_hands = {player: [] for player in PLAYERS}
    full_hands.update(
        {
            player: [card(suit, rank) for suit, rank in player_cards]
            for player, player_cards in hands.items()
        }
    )
    entries = [
        {"player": player, "card": card(suit, rank)}
        for player, suit, rank in (trick or [])
    ]
    caller = PLAYERS[(PLAYERS.index(dealer) + 1) % len(PLAYERS)]
    return {
        "game": "rang",
        "phase": "playing",
        "players": list(PLAYERS),
        "teams": [["alice", "cara"], ["bob", "dan"]],
        "dealer": dealer,
        "trump_caller": caller,
        "trump": trump,
        "hands": full_hands,
        "stock": [],
        "current_player": current_player,
        "trick": entries,
        "team_tricks": list(team_tricks),
        "deal_streaks": list(deal_streaks),
        "courts": list(courts),
        "court_target": court_target,
        "deal_number": 1,
        "winner_team": None,
        "timeout_counts": {
            player: (timeout_counts or {}).get(player, 0) for player in PLAYERS
        },
        "paused_player": None,
        "paused_phase": None,
        "shuffle_seed": 8675309,
    }


def deal_closing_state(
    winning_team,
    *,
    dealer,
    team_tricks,
    deal_streaks=(0, 0),
    courts=(0, 0),
    court_target=3,
):
    if winning_team == 1:
        trick = [
            ("alice", "hearts", "A"),
            ("bob", "hearts", "2"),
            ("cara", "hearts", "3"),
        ]
        final_card = ("hearts", "4")
    else:
        trick = [
            ("alice", "hearts", "2"),
            ("bob", "hearts", "A"),
            ("cara", "hearts", "3"),
        ]
        final_card = ("hearts", "K")
    return playing_state(
        {"dan": [final_card]},
        "dan",
        trick=trick,
        trump="clubs",
        dealer=dealer,
        team_tricks=team_tricks,
        deal_streaks=deal_streaks,
        courts=courts,
        court_target=court_target,
    )


class RangRulesTests(unittest.TestCase):
    def test_new_game_requires_four_unique_players_and_positive_target(self):
        invalid_players = (
            PLAYERS[:3],
            PLAYERS + ["eve"],
            ["alice", "alice", "cara", "dan"],
            ["alice", "bob", "", "dan"],
        )
        for players in invalid_players:
            with self.subTest(players=players):
                with self.assertRaises(ValueError):
                    new_game(players, random.Random(7))

        for target in (0, -1, 1.5, True):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    new_game(PLAYERS, random.Random(7), court_target=target)

    def test_new_game_sets_fixed_teams_and_deals_five_before_trump(self):
        state = new_game(PLAYERS, random.Random(17), court_target=3)

        dealer_index = PLAYERS.index(state["dealer"])
        self.assertEqual([["alice", "cara"], ["bob", "dan"]], state["teams"])
        self.assertEqual(PLAYERS[(dealer_index + 1) % 4], state["trump_caller"])
        self.assertEqual("choosing_trump", state["phase"])
        self.assertEqual(state["trump_caller"], state["current_player"])
        self.assertIsNone(state["trump"])
        self.assertEqual([5, 5, 5, 5], [len(state["hands"][p]) for p in PLAYERS])
        self.assertEqual(32, len(state["stock"]))
        all_ids = [
            dealt["id"]
            for player in PLAYERS
            for dealt in state["hands"][player]
        ] + [dealt["id"] for dealt in state["stock"]]
        self.assertEqual(52, len(set(all_ids)))
        self.assertEqual(3, state["court_target"])
        self.assertEqual(state, new_game(PLAYERS, random.Random(17), court_target=3))
        json.dumps(state, allow_nan=False)

    def test_only_caller_can_choose_valid_trump_then_deal_completes(self):
        state = new_game(PLAYERS, random.Random(23))
        caller = state["trump_caller"]

        for user, suit in ((state["dealer"], "hearts"), (caller, "stars")):
            with self.subTest(user=user, suit=suit):
                before = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    choose_trump(state, user, suit)
                self.assertEqual(before, state)

        event = choose_trump(state, caller, "diamonds")

        self.assertEqual(
            {"kind": "trump", "player": caller, "trump": "diamonds"}, event
        )
        self.assertEqual("playing", state["phase"])
        self.assertEqual(caller, state["current_player"])
        self.assertEqual("diamonds", state["trump"])
        self.assertEqual([13, 13, 13, 13], [len(state["hands"][p]) for p in PLAYERS])
        self.assertEqual([], state["stock"])
        json.dumps(state, allow_nan=False)
        json.dumps(event, allow_nan=False)

    def test_player_must_follow_led_suit_when_holding_it(self):
        state = playing_state(
            {"bob": [("diamonds", "2"), ("clubs", "A")]},
            "bob",
            trick=[("alice", "diamonds", "10")],
        )

        self.assertEqual({card_id("diamonds", "2")}, legal_card_ids(state, "bob"))
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            play(state, "bob", card_id("clubs", "A"))
        self.assertEqual(before, state)

    def test_player_without_led_suit_may_play_any_card(self):
        state = playing_state(
            {"bob": [("clubs", "2"), ("spades", "A")]},
            "bob",
            trick=[("alice", "diamonds", "10")],
        )

        self.assertEqual(
            {card_id("clubs", "2"), card_id("spades", "A")},
            legal_card_ids(state, "bob"),
        )

    def test_highest_led_suit_wins_when_no_trump_is_played(self):
        state = playing_state(
            {"dan": [("hearts", "Q")]},
            "dan",
            trick=[
                ("alice", "hearts", "10"),
                ("bob", "hearts", "K"),
                ("cara", "hearts", "3"),
            ],
            trump="clubs",
        )

        event = play(state, "dan", card_id("hearts", "Q"))

        self.assertEqual("trick", event["kind"])
        self.assertEqual("bob", event["winner"])
        self.assertEqual(2, event["winning_team"])
        self.assertEqual("bob", state["current_player"])
        self.assertEqual([0, 1], state["team_tricks"])
        self.assertEqual([], state["trick"])

    def test_highest_trump_wins_over_led_suit(self):
        state = playing_state(
            {"dan": [("spades", "K")]},
            "dan",
            trick=[
                ("alice", "hearts", "10"),
                ("bob", "spades", "2"),
                ("cara", "hearts", "A"),
            ],
            trump="spades",
        )

        event = play(state, "dan", card_id("spades", "K"))

        self.assertEqual("dan", event["winner"])
        self.assertEqual(2, event["winning_team"])
        self.assertEqual("dan", state["current_player"])

    def test_seven_tricks_wins_deal_and_opponent_win_breaks_streak(self):
        state = deal_closing_state(
            2,
            dealer="alice",
            team_tricks=(5, 6),
            deal_streaks=(5, 0),
        )

        event = play(state, "dan", card_id("hearts", "K"))

        self.assertEqual(2, event["deal_winner"])
        self.assertFalse(event["court"])
        self.assertEqual([0, 1], state["deal_streaks"])
        self.assertEqual([0, 0], state["team_tricks"])
        self.assertEqual(2, state["deal_number"])
        self.assertEqual("choosing_trump", state["phase"])
        self.assertEqual([5, 5, 5, 5], [len(state["hands"][p]) for p in PLAYERS])

    def test_first_seven_tricks_scores_immediate_court(self):
        state = deal_closing_state(
            1,
            dealer="bob",
            team_tricks=(6, 0),
            deal_streaks=(4, 0),
        )

        event = play(state, "dan", card_id("hearts", "4"))

        self.assertTrue(event["court"])
        self.assertEqual(1, event["court_winner"])
        self.assertEqual([1, 0], state["courts"])
        self.assertEqual([0, 0], state["deal_streaks"])
        self.assertEqual("dan", state["dealer"])

    def test_seven_consecutive_deal_wins_scores_court_and_resets_streak(self):
        state = deal_closing_state(
            1,
            dealer="bob",
            team_tricks=(6, 2),
            deal_streaks=(6, 0),
        )

        event = play(state, "dan", card_id("hearts", "4"))

        self.assertTrue(event["court"])
        self.assertEqual(1, event["court_winner"])
        self.assertEqual([1, 0], state["courts"])
        self.assertEqual([0, 0], state["deal_streaks"])

    def test_dealer_transitions_follow_dealer_and_caller_team_results(self):
        cases = (
            {
                "name": "dealer team wins",
                "dealer": "alice",
                "winner": 1,
                "tricks": (6, 2),
                "streaks": (0, 0),
                "expected": "bob",
            },
            {
                "name": "caller team wins ordinary deal",
                "dealer": "bob",
                "winner": 1,
                "tricks": (6, 2),
                "streaks": (0, 0),
                "expected": "bob",
            },
            {
                "name": "caller team scores court",
                "dealer": "bob",
                "winner": 1,
                "tricks": (6, 0),
                "streaks": (0, 0),
                "expected": "dan",
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                state = deal_closing_state(
                    case["winner"],
                    dealer=case["dealer"],
                    team_tricks=case["tricks"],
                    deal_streaks=case["streaks"],
                )
                final_rank = "4" if case["winner"] == 1 else "K"

                play(state, "dan", card_id("hearts", final_rank))

                self.assertEqual(case["expected"], state["dealer"])
                expected_caller = PLAYERS[(PLAYERS.index(case["expected"]) + 1) % 4]
                self.assertEqual(expected_caller, state["trump_caller"])

    def test_reaching_configured_court_target_finishes_session(self):
        continuing = deal_closing_state(
            1,
            dealer="bob",
            team_tricks=(6, 0),
            court_target=2,
        )
        play(continuing, "dan", card_id("hearts", "4"))
        self.assertEqual("choosing_trump", continuing["phase"])

        winning = deal_closing_state(
            1,
            dealer="bob",
            team_tricks=(6, 0),
            courts=(1, 0),
            court_target=2,
        )
        event = play(winning, "dan", card_id("hearts", "4"))

        self.assertEqual("finished", winning["phase"])
        self.assertEqual(1, winning["winner_team"])
        self.assertIsNone(winning["current_player"])
        self.assertEqual(1, event["court_winner"])
        self.assertTrue(event["finished"])

    def test_auto_play_uses_lowest_ranked_legal_card(self):
        state = playing_state(
            {
                "bob": [
                    ("hearts", "10"),
                    ("hearts", "2"),
                    ("clubs", "2"),
                ]
            },
            "bob",
            trick=[("alice", "hearts", "K")],
        )

        event = auto_play(state, "bob")

        self.assertEqual(card_id("hearts", "2"), event["card"]["id"])
        self.assertTrue(event["automatic"])
        self.assertEqual(1, state["timeout_counts"]["bob"])

    def test_third_timeout_pauses_until_absent_player_resumes(self):
        state = playing_state(
            {
                "bob": [("hearts", "2")],
                "cara": [("hearts", "3")],
                "dan": [("hearts", "4")],
            },
            "bob",
            trick=[("alice", "hearts", "K")],
            timeout_counts={"bob": 2},
        )

        event = auto_play(state, "bob")

        self.assertTrue(event["paused"])
        self.assertEqual("paused", state["phase"])
        self.assertEqual("bob", state["paused_player"])
        self.assertEqual("playing", state["paused_phase"])
        self.assertEqual("cara", state["current_player"])

        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            play(state, "cara", card_id("hearts", "3"))
        self.assertEqual(before, state)
        with self.assertRaises(ValueError):
            resume(state, "alice")
        self.assertEqual(before, state)

        resumed = resume(state, "bob")
        self.assertEqual({"kind": "resume", "player": "bob"}, resumed)
        self.assertEqual("playing", state["phase"])
        self.assertIsNone(state["paused_player"])
        self.assertIsNone(state["paused_phase"])
        self.assertEqual(0, state["timeout_counts"]["bob"])
        play(state, "cara", card_id("hearts", "3"))
        json.dumps(state, allow_nan=False)

    def test_manual_play_resets_that_players_timeout_count(self):
        state = playing_state(
            {"bob": [("hearts", "2")]},
            "bob",
            trick=[("alice", "hearts", "K")],
            timeout_counts={"bob": 2},
        )

        play(state, "bob", card_id("hearts", "2"))

        self.assertEqual(0, state["timeout_counts"]["bob"])

    def test_public_view_hides_private_cards_and_internal_shuffle_state(self):
        state = new_game(PLAYERS, random.Random(31), court_target=4)

        view = public_view(state)

        for private_key in (
            "hands",
            "stock",
            "shuffle_seed",
            "timeout_counts",
            "paused_phase",
        ):
            self.assertNotIn(private_key, view)
        self.assertEqual({player: 5 for player in PLAYERS}, view["card_counts"])
        self.assertEqual(state["teams"], view["teams"])
        self.assertEqual(4, view["court_target"])
        json.dumps(view, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
