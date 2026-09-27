import copy
import json
import random
import unittest

from services.cards import card_to_dict, uno_deck
from services.uno import (
    auto_turn,
    call_uno,
    catch_uno,
    challenge_wild4,
    choose_color,
    draw,
    legal_card_ids,
    new_match,
    play,
    public_view,
)


PLAYERS = ["alice", "bob", "cara"]
DECK = [card_to_dict(card) for card in uno_deck()]


class FixedRng:
    def __init__(self, value):
        self.value = value

    def randrange(self, _limit):
        return self.value


def card(suit, rank, copy_index=0):
    matches = [item for item in DECK if item["suit"] == suit and item["rank"] == rank]
    return copy.deepcopy(matches[copy_index])


def playing_state(
    hands,
    current_player="alice",
    *,
    top=None,
    active_color=None,
    direction=1,
    pending_draw=0,
    pending_draw_type=None,
    draw_top=None,
    scores=None,
    target=500,
):
    players = list(hands)
    top_card = copy.deepcopy(top or card("red", "5"))
    copied_hands = {
        player: [copy.deepcopy(item) for item in player_cards]
        for player, player_cards in hands.items()
    }
    used_ids = {top_card["id"]}
    used_ids.update(
        item["id"] for player_cards in copied_hands.values() for item in player_cards
    )
    draw_pile = [copy.deepcopy(item) for item in DECK if item["id"] not in used_ids]
    if draw_top is not None:
        draw_pile = [item for item in draw_pile if item["id"] != draw_top["id"]]
        draw_pile.append(copy.deepcopy(draw_top))
    return {
        "game": "uno",
        "phase": "playing",
        "players": players,
        "hands": copied_hands,
        "draw_pile": draw_pile,
        "discard_pile": [top_card],
        "current_player": current_player,
        "direction": direction,
        "active_color": active_color or top_card["suit"],
        "pending_draw": pending_draw,
        "pending_draw_type": pending_draw_type,
        "drawn_card_id": None,
        "color_chooser": None,
        "wild4_offender": None,
        "wild4_target": None,
        "wild4_had_active_color": None,
        "uno_window": None,
        "scores": {
            player: (scores or {}).get(player, 0) for player in players
        },
        "target": target,
        "round_number": 1,
        "winner": None,
        "pending_round_candidates": [],
        "timeout_counts": {player: 0 for player in players},
        "removed_players": [],
        "shuffle_seed": 8675309,
        "shuffle_counter": 0,
    }


def all_card_ids(state):
    return {
        item["id"]
        for item in (
            state["draw_pile"]
            + state["discard_pile"]
            + [card_item for hand in state["hands"].values() for card_item in hand]
        )
    }


class UnoRulesTests(unittest.TestCase):
    def test_new_match_accepts_two_through_ten_unique_players(self):
        for count in (2, 10):
            with self.subTest(count=count):
                players = [f"p{index}" for index in range(count)]
                state = new_match(players, random.Random(17))
                self.assertEqual(players, state["players"])

        invalid_groups = (
            ["alice"],
            [f"p{index}" for index in range(11)],
            ["alice", "alice"],
            ["alice", ""],
        )
        for players in invalid_groups:
            with self.subTest(players=players):
                with self.assertRaises(ValueError):
                    new_match(players, random.Random(17))

        for target in (0, -1, 1.5, True):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    new_match(["alice", "bob"], random.Random(17), target=target)

    def test_new_match_deals_seven_unique_cards_and_is_deterministic(self):
        players = [f"p{index}" for index in range(10)]

        state = new_match(players, random.Random(23), target=700)

        self.assertEqual([7] * 10, [len(state["hands"][p]) for p in players])
        all_cards = [
            item
            for player in players
            for item in state["hands"][player]
        ] + state["draw_pile"] + state["discard_pile"]
        self.assertEqual(108, len(all_cards))
        self.assertEqual(108, len({item["id"] for item in all_cards}))
        self.assertNotEqual("wild4", state["discard_pile"][-1]["rank"])
        self.assertEqual("p0", state["current_player"])
        self.assertEqual(700, state["target"])
        self.assertEqual(state, new_match(players, random.Random(23), target=700))
        json.dumps(state, allow_nan=False)

    def test_opening_skip_reverse_and_draw_two_apply_standard_effects(self):
        cases = (
            ("skip", 0, "bob", 1, 7),
            ("reverse", 14, "cara", -1, 7),
            ("draw2", 16, "bob", 1, 9),
        )
        for expected_rank, seed, current_player, direction, alice_cards in cases:
            with self.subTest(rank=expected_rank):
                state = new_match(PLAYERS, FixedRng(seed))

                self.assertEqual(expected_rank, state["discard_pile"][-1]["rank"])
                self.assertEqual(current_player, state["current_player"])
                self.assertEqual(direction, state["direction"])
                self.assertEqual(alice_cards, len(state["hands"]["alice"]))
                self.assertEqual(0, state["pending_draw"])

    def test_opening_wild_lets_first_player_choose_color_and_keep_turn(self):
        state = new_match(PLAYERS, FixedRng(5))

        self.assertEqual("wild", state["discard_pile"][-1]["rank"])
        self.assertEqual("choosing_color", state["phase"])
        self.assertEqual("alice", state["color_chooser"])
        self.assertEqual("alice", state["current_player"])

        choose_color(state, "alice", "blue")

        self.assertEqual("playing", state["phase"])
        self.assertEqual("blue", state["active_color"])
        self.assertEqual("alice", state["current_player"])

    def test_opening_wild_draw_four_is_returned_and_redrawn_deterministically(self):
        first = new_match(PLAYERS, FixedRng(95))
        second = new_match(PLAYERS, FixedRng(95))

        self.assertEqual(first, second)
        self.assertEqual("u49", first["discard_pile"][-1]["id"])
        self.assertEqual("draw2", first["discard_pile"][-1]["rank"])
        self.assertEqual(9, len(first["hands"]["alice"]))
        self.assertEqual("bob", first["current_player"])
        self.assertEqual(108, len(all_card_ids(first)))

    def test_cards_match_by_color_number_or_action_symbol(self):
        red_nine = card("red", "9")
        blue_five = card("blue", "5")
        blue_reverse = card("blue", "reverse")
        wild = card("wild", "wild")
        yellow_seven = card("yellow", "7")
        state = playing_state(
            {
                "alice": [red_nine, blue_five, blue_reverse, wild, yellow_seven],
                "bob": [card("green", "1")],
            }
        )

        self.assertEqual(
            {red_nine["id"], blue_five["id"], wild["id"]},
            legal_card_ids(state, "alice"),
        )

        symbol_state = playing_state(
            {
                "alice": [card("yellow", "skip"), card("yellow", "3")],
                "bob": [card("green", "1")],
            },
            top=card("red", "skip"),
        )
        self.assertEqual(
            {symbol_state["hands"]["alice"][0]["id"]},
            legal_card_ids(symbol_state, "alice"),
        )

    def test_illegal_wild_draw_four_is_exposed_by_a_successful_challenge(self):
        wild4 = card("wild", "wild4")
        state = playing_state(
            {
                "alice": [wild4, card("red", "2")],
                "bob": [card("green", "1")],
            }
        )
        before_count = len(state["hands"]["alice"])

        self.assertIn(wild4["id"], legal_card_ids(state, "alice"))
        play(state, "alice", wild4["id"])
        self.assertTrue(state["wild4_had_active_color"])
        choose_color(state, "alice", "blue")
        event = challenge_wild4(state, "bob")

        self.assertTrue(event["successful"])
        self.assertEqual("alice", event["drawn_by"])
        self.assertEqual(before_count - 1 + 4, len(state["hands"]["alice"]))
        self.assertEqual("bob", state["current_player"])

    def test_reverse_changes_direction_with_three_players(self):
        reverse = card("red", "reverse")
        state = playing_state(
            {
                "alice": [reverse, card("blue", "1")],
                "bob": [card("green", "1")],
                "cara": [card("yellow", "1")],
            }
        )

        play(state, "alice", reverse["id"])

        self.assertEqual(-1, state["direction"])
        self.assertEqual("cara", state["current_player"])

    def test_reverse_and_skip_return_turn_to_player_in_two_player_game(self):
        for rank in ("reverse", "skip"):
            with self.subTest(rank=rank):
                action = card("red", rank)
                state = playing_state(
                    {
                        "alice": [action, card("blue", "1")],
                        "bob": [card("green", "1")],
                    }
                )

                play(state, "alice", action["id"])

                self.assertEqual("alice", state["current_player"])
                expected_direction = -1 if rank == "reverse" else 1
                self.assertEqual(expected_direction, state["direction"])

    def test_draw_two_stacks_only_on_draw_two(self):
        first = card("red", "draw2")
        second = card("blue", "draw2")
        wild4 = card("wild", "wild4")
        state = playing_state(
            {
                "alice": [first, card("yellow", "1")],
                "bob": [second, wild4, card("green", "1")],
                "cara": [card("blue", "1")],
            }
        )

        play(state, "alice", first["id"])

        self.assertEqual(2, state["pending_draw"])
        self.assertEqual("draw2", state["pending_draw_type"])
        self.assertEqual({second["id"]}, legal_card_ids(state, "bob"))
        play(state, "bob", second["id"])
        self.assertEqual(4, state["pending_draw"])
        self.assertEqual("cara", state["current_player"])

    def test_drawing_an_accumulated_penalty_takes_all_cards_and_passes(self):
        state = playing_state(
            {
                "alice": [card("red", "draw2"), card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            },
            pending_draw=4,
            pending_draw_type="draw2",
            current_player="bob",
        )
        before_count = len(state["hands"]["bob"])

        event = draw(state, "bob")

        self.assertEqual(4, event["count"])
        self.assertTrue(event["penalty"])
        self.assertEqual(before_count + 4, len(state["hands"]["bob"]))
        self.assertEqual(0, state["pending_draw"])
        self.assertIsNone(state["pending_draw_type"])
        self.assertEqual("cara", state["current_player"])

    def test_playable_drawn_card_is_the_only_immediate_play_option(self):
        already_playable = card("red", "9")
        drawn = card("blue", "5")
        state = playing_state(
            {
                "alice": [already_playable, card("yellow", "1")],
                "bob": [card("green", "1")],
            },
            draw_top=drawn,
        )

        event = draw(state, "alice")

        self.assertTrue(event["playable"])
        self.assertFalse(event["passed"])
        self.assertEqual("alice", state["current_player"])
        self.assertEqual(drawn["id"], state["drawn_card_id"])
        self.assertEqual({drawn["id"]}, legal_card_ids(state, "alice"))
        play(state, "alice", drawn["id"])
        self.assertEqual("bob", state["current_player"])
        self.assertIsNone(state["drawn_card_id"])

    def test_unplayable_drawn_card_passes_turn(self):
        drawn = card("blue", "8")
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "1")],
            },
            draw_top=drawn,
        )

        event = draw(state, "alice")

        self.assertFalse(event["playable"])
        self.assertTrue(event["passed"])
        self.assertEqual("bob", state["current_player"])
        self.assertIsNone(state["drawn_card_id"])

    def test_player_may_decline_playable_draw_without_drawing_again(self):
        drawn = card("blue", "5")
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "1")],
            },
            draw_top=drawn,
        )
        draw(state, "alice")
        pile_count = len(state["draw_pile"])

        event = draw(state, "alice")

        self.assertEqual(0, event["count"])
        self.assertTrue(event["passed"])
        self.assertEqual(pile_count, len(state["draw_pile"]))
        self.assertEqual("bob", state["current_player"])

    def test_wild_requires_valid_color_choice_before_turn_advances(self):
        wild = card("wild", "wild")
        state = playing_state(
            {
                "alice": [wild, card("yellow", "1")],
                "bob": [card("green", "1")],
            }
        )

        event = play(state, "alice", wild["id"])

        self.assertTrue(event["requires_color"])
        self.assertEqual("choosing_color", state["phase"])
        self.assertEqual("alice", state["current_player"])
        for user, color_name in (("bob", "blue"), ("alice", "purple")):
            with self.subTest(user=user, color=color_name):
                before = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    choose_color(state, user, color_name)
                self.assertEqual(before, state)

        chosen = choose_color(state, "alice", "blue")
        self.assertEqual({"kind": "color", "player": "alice", "color": "blue"}, chosen)
        self.assertEqual("playing", state["phase"])
        self.assertEqual("blue", state["active_color"])
        self.assertEqual("bob", state["current_player"])

    def test_wild_draw_four_stores_private_fact_and_failed_challenge_draws_six(self):
        wild4 = card("wild", "wild4")
        state = playing_state(
            {
                "alice": [wild4, card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            }
        )

        play(state, "alice", wild4["id"])

        self.assertFalse(state["wild4_had_active_color"])
        self.assertNotIn("wild4_had_active_color", public_view(state))
        choose_color(state, "alice", "green")
        self.assertEqual(4, state["pending_draw"])
        self.assertEqual("wild4", state["pending_draw_type"])
        self.assertEqual("bob", state["wild4_target"])
        before_count = len(state["hands"]["bob"])

        event = challenge_wild4(state, "bob")

        self.assertFalse(event["successful"])
        self.assertEqual(6, event["count"])
        self.assertEqual(before_count + 6, len(state["hands"]["bob"]))
        self.assertEqual("cara", state["current_player"])
        self.assertEqual(0, state["pending_draw"])

    def test_successful_wild_draw_four_challenge_moves_penalty_to_offender(self):
        wild4 = card("wild", "wild4")
        state = playing_state(
            {
                "alice": [wild4, card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            }
        )
        play(state, "alice", wild4["id"])
        choose_color(state, "alice", "green")
        state["wild4_had_active_color"] = True
        before_count = len(state["hands"]["alice"])

        event = challenge_wild4(state, "bob")

        self.assertTrue(event["successful"])
        self.assertEqual(4, event["count"])
        self.assertEqual("alice", event["drawn_by"])
        self.assertEqual(before_count + 4, len(state["hands"]["alice"]))
        self.assertEqual("bob", state["current_player"])
        self.assertEqual(0, state["pending_draw"])

    def test_wild_draw_four_stacks_only_on_wild_draw_four(self):
        first = card("wild", "wild4", 0)
        second = card("wild", "wild4", 1)
        draw_two = card("green", "draw2")
        state = playing_state(
            {
                "alice": [first, card("yellow", "1")],
                "bob": [second, draw_two, card("blue", "1")],
                "cara": [card("green", "1")],
            }
        )
        play(state, "alice", first["id"])
        choose_color(state, "alice", "red")

        self.assertEqual({second["id"]}, legal_card_ids(state, "bob"))
        play(state, "bob", second["id"])
        choose_color(state, "bob", "green")
        self.assertEqual(8, state["pending_draw"])
        self.assertEqual("cara", state["current_player"])

    def test_player_can_call_uno_after_reaching_one_card(self):
        played = card("red", "2")
        state = playing_state(
            {
                "alice": [played, card("yellow", "1")],
                "bob": [card("green", "1")],
            }
        )
        play(state, "alice", played["id"])

        event = call_uno(state, "alice")

        self.assertEqual({"kind": "uno", "player": "alice"}, event)
        self.assertIsNone(state["uno_window"])
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            catch_uno(state, "bob")
        self.assertEqual(before, state)

    def test_other_player_can_catch_missed_uno_before_next_action(self):
        played = card("red", "2")
        state = playing_state(
            {
                "alice": [played, card("yellow", "1")],
                "bob": [card("green", "5")],
            }
        )
        play(state, "alice", played["id"])
        before_count = len(state["hands"]["alice"])

        event = catch_uno(state, "bob")

        self.assertEqual("alice", event["caught"])
        self.assertEqual(2, event["count"])
        self.assertEqual(before_count + 2, len(state["hands"]["alice"]))
        self.assertEqual("bob", state["current_player"])
        self.assertIsNone(state["uno_window"])

    def test_uno_catch_window_closes_when_next_player_acts(self):
        played = card("red", "2")
        response = card("red", "7")
        state = playing_state(
            {
                "alice": [played, card("yellow", "1")],
                "bob": [response, card("green", "1"), card("blue", "3")],
                "cara": [card("blue", "1")],
            }
        )
        play(state, "alice", played["id"])
        play(state, "bob", response["id"])

        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            catch_uno(state, "cara")
        self.assertEqual(before, state)

    def test_round_scores_opponents_cards_and_redeals_automatically(self):
        winning_card = card("red", "7")
        state = playing_state(
            {
                "alice": [winning_card],
                "bob": [card("blue", "draw2")],
                "cara": [card("wild", "wild"), card("yellow", "9")],
            }
        )

        event = play(state, "alice", winning_card["id"])

        self.assertEqual("round", event["kind"])
        self.assertEqual("alice", event["round_winner"])
        self.assertEqual(79, event["points"])
        self.assertEqual(79, state["scores"]["alice"])
        self.assertEqual(2, state["round_number"])
        self.assertEqual("playing", state["phase"])
        self.assertEqual([7, 7, 7], [len(state["hands"][p]) for p in PLAYERS])
        self.assertIsNone(state["winner"])

    def test_final_plain_wild_finishes_round_without_color_selection(self):
        wild = card("wild", "wild")
        state = playing_state(
            {
                "alice": [wild],
                "bob": [card("blue", "3")],
            }
        )

        event = play(state, "alice", wild["id"])

        self.assertEqual("round", event["kind"])
        self.assertEqual("alice", event["round_winner"])
        self.assertEqual(3, event["points"])
        self.assertEqual("playing", state["phase"])
        self.assertEqual(2, state["round_number"])
        self.assertIsNone(state["color_chooser"])

    def test_zero_card_draw_two_stacker_wins_if_first_candidate_draws(self):
        first = card("red", "draw2")
        second = card("blue", "draw2")
        state = playing_state({"alice": [first], "bob": [second]})

        play(state, "alice", first["id"])
        play(state, "bob", second["id"])
        event = draw(state, "alice")

        self.assertEqual("round", event["kind"])
        self.assertEqual("bob", event["round_winner"])
        self.assertGreater(event["points"], 0)
        self.assertEqual(2, state["round_number"])

    def test_zero_card_wild4_stacker_wins_when_first_candidate_loses_challenge(self):
        first = card("wild", "wild4", 0)
        second = card("wild", "wild4", 1)
        state = playing_state({"alice": [first], "bob": [second]})

        play(state, "alice", first["id"])
        choose_color(state, "alice", "red")
        play(state, "bob", second["id"])
        choose_color(state, "bob", "blue")
        event = challenge_wild4(state, "alice")

        self.assertEqual("round", event["kind"])
        self.assertEqual("bob", event["round_winner"])
        self.assertGreater(event["points"], 0)
        self.assertEqual(2, state["round_number"])

    def test_final_draw_two_scores_after_target_draws_penalty(self):
        draw_two = card("red", "draw2")
        state = playing_state(
            {"alice": [draw_two], "bob": [card("blue", "3")]}
        )

        play(state, "alice", draw_two["id"])
        event = draw(state, "bob")

        self.assertEqual("round", event["kind"])
        self.assertEqual("alice", event["round_winner"])
        self.assertGreater(event["points"], 3)

    def test_final_wild4_scores_after_target_draws_penalty(self):
        wild4 = card("wild", "wild4")
        state = playing_state(
            {"alice": [wild4], "bob": [card("blue", "3")]}
        )

        play(state, "alice", wild4["id"])
        choose_color(state, "alice", "green")
        event = draw(state, "bob")

        self.assertEqual("round", event["kind"])
        self.assertEqual("alice", event["round_winner"])
        self.assertGreater(event["points"], 3)

    def test_final_wild4_scores_after_failed_challenge(self):
        wild4 = card("wild", "wild4")
        state = playing_state(
            {"alice": [wild4], "bob": [card("blue", "3")]}
        )

        play(state, "alice", wild4["id"])
        choose_color(state, "alice", "green")
        event = challenge_wild4(state, "bob")

        self.assertEqual("round", event["kind"])
        self.assertEqual("alice", event["round_winner"])
        self.assertGreater(event["points"], 3)

    def test_final_reverse_and_skip_finish_round_immediately(self):
        for rank in ("reverse", "skip"):
            with self.subTest(rank=rank):
                action = card("red", rank)
                state = playing_state(
                    {"alice": [action], "bob": [card("blue", "3")]}
                )

                event = play(state, "alice", action["id"])

                self.assertEqual("round", event["kind"])
                self.assertEqual("alice", event["round_winner"])
                self.assertEqual(3, event["points"])

    def test_first_player_to_target_finishes_match_without_redeal(self):
        winning_card = card("red", "7")
        state = playing_state(
            {
                "alice": [winning_card],
                "bob": [card("blue", "1")],
            },
            scores={"alice": 499},
        )

        event = play(state, "alice", winning_card["id"])

        self.assertEqual("round", event["kind"])
        self.assertEqual("alice", event["match_winner"])
        self.assertEqual(500, state["scores"]["alice"])
        self.assertEqual("finished", state["phase"])
        self.assertEqual("alice", state["winner"])
        self.assertIsNone(state["current_player"])

    def test_public_view_has_exact_room_safe_schema(self):
        state = new_match(PLAYERS, random.Random(31))

        view = public_view(state)

        self.assertEqual(
            {
                "game",
                "phase",
                "players",
                "current_player",
                "direction",
                "active_color",
                "discard",
                "draw_count",
                "card_counts",
                "pending_draw",
                "pending_draw_type",
                "color_chooser",
                "challenge",
                "uno_catchable",
                "scores",
                "target",
                "round_number",
                "winner",
                "removed_players",
            },
            set(view),
        )
        self.assertEqual({player: 7 for player in PLAYERS}, view["card_counts"])
        self.assertEqual(state["discard_pile"][-1], view["discard"])
        json.dumps(view, allow_nan=False)

    def test_recycling_retains_top_card_conserves_ids_and_is_deterministic(self):
        state = playing_state(
            {
                "alice": [card("yellow", "9")],
                "bob": [card("green", "1")],
            },
            top=card("red", "5"),
        )
        state["draw_pile"] = []
        state["discard_pile"] = [
            card("red", "1"),
            card("yellow", "2"),
            card("green", "3"),
            card("red", "5"),
        ]
        twin = copy.deepcopy(state)
        ids_before = all_card_ids(state)
        top_before = copy.deepcopy(state["discard_pile"][-1])

        first_event = draw(state, "alice")
        second_event = draw(twin, "alice")

        self.assertEqual(first_event, second_event)
        self.assertEqual(state, twin)
        self.assertEqual([top_before], state["discard_pile"])
        self.assertEqual(ids_before, all_card_ids(state))

    def test_auto_turn_draws_one_and_passes_even_when_card_is_playable(self):
        drawn = card("blue", "5")
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            },
            draw_top=drawn,
        )
        before_count = len(state["hands"]["alice"])

        event = auto_turn(state, "alice")

        self.assertTrue(event["automatic"])
        self.assertEqual(1, event["count"])
        self.assertEqual(before_count + 1, len(state["hands"]["alice"]))
        self.assertEqual("bob", state["current_player"])
        self.assertIsNone(state["drawn_card_id"])
        self.assertEqual(1, state["timeout_counts"]["alice"])

    def test_auto_turn_takes_accumulated_penalty_and_passes_once(self):
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "draw2")],
                "cara": [card("blue", "1")],
            },
            current_player="bob",
            pending_draw=6,
            pending_draw_type="draw2",
        )
        before_count = len(state["hands"]["bob"])

        event = auto_turn(state, "bob")

        self.assertEqual(6, event["count"])
        self.assertTrue(event["penalty"])
        self.assertEqual(before_count + 6, len(state["hands"]["bob"]))
        self.assertEqual("cara", state["current_player"])
        self.assertEqual(0, state["pending_draw"])

    def test_third_timeout_removes_player_when_two_can_continue(self):
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            }
        )
        state["timeout_counts"]["alice"] = 2
        total_before = (
            sum(len(items) for items in state["hands"].values())
            + len(state["draw_pile"])
            + len(state["discard_pile"])
        )

        event = auto_turn(state, "alice")

        total_after = (
            sum(len(items) for items in state["hands"].values())
            + len(state["draw_pile"])
            + len(state["discard_pile"])
        )
        self.assertTrue(event["removed"])
        self.assertEqual(["bob", "cara"], state["players"])
        self.assertEqual(["alice"], state["removed_players"])
        self.assertNotIn("alice", state["hands"])
        self.assertNotIn("alice", state["scores"])
        self.assertNotIn("alice", state["timeout_counts"])
        self.assertEqual("bob", state["current_player"])
        self.assertEqual(total_before, total_after)

    def test_third_timeout_does_not_remove_from_two_player_match(self):
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "1")],
            }
        )
        state["timeout_counts"]["alice"] = 2

        event = auto_turn(state, "alice")

        self.assertFalse(event["removed"])
        self.assertEqual(["alice", "bob"], state["players"])
        self.assertEqual(3, state["timeout_counts"]["alice"])
        self.assertEqual("bob", state["current_player"])

    def test_auto_turn_selects_a_deterministic_color_for_pending_wild(self):
        wild = card("wild", "wild")
        state = playing_state(
            {
                "alice": [wild, card("blue", "1"), card("blue", "2")],
                "bob": [card("green", "1")],
            }
        )
        play(state, "alice", wild["id"])

        event = auto_turn(state, "alice")

        self.assertTrue(event["automatic"])
        self.assertEqual("blue", event["color"])
        self.assertEqual("blue", state["active_color"])
        self.assertEqual("bob", state["current_player"])
        self.assertEqual(1, state["timeout_counts"]["alice"])

    def test_all_rejected_mutators_leave_state_unchanged(self):
        base = playing_state(
            {
                "alice": [card("red", "2"), card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            }
        )
        challenge_state = playing_state(
            {
                "alice": [card("wild", "wild4"), card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            }
        )
        play(challenge_state, "alice", challenge_state["hands"]["alice"][0]["id"])
        choose_color(challenge_state, "alice", "green")
        cases = (
            ("play", copy.deepcopy(base), lambda state: play(state, "alice", "u9999")),
            ("draw", copy.deepcopy(base), lambda state: draw(state, "bob")),
            (
                "choose_color",
                copy.deepcopy(base),
                lambda state: choose_color(state, "alice", "blue"),
            ),
            (
                "challenge_wild4",
                challenge_state,
                lambda state: challenge_wild4(state, "cara"),
            ),
            ("call_uno", copy.deepcopy(base), lambda state: call_uno(state, "alice")),
            ("catch_uno", copy.deepcopy(base), lambda state: catch_uno(state, "bob")),
            ("auto_turn", copy.deepcopy(base), lambda state: auto_turn(state, "bob")),
        )
        for name, state, rejected in cases:
            with self.subTest(mutator=name):
                before = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    rejected(state)
                self.assertEqual(before, state)

    def test_forged_and_stale_card_ids_never_mutate_state(self):
        playable = card("red", "2")
        state = playing_state(
            {
                "alice": [playable, card("yellow", "1")],
                "bob": [card("green", "1")],
            }
        )

        play(state, "alice", playable["id"])
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            play(state, "alice", playable["id"])
        self.assertEqual(before, state)

    def test_each_accepted_manual_draw_advances_exactly_one_turn(self):
        state = playing_state(
            {
                "alice": [card("yellow", "1")],
                "bob": [card("green", "1")],
                "cara": [card("blue", "1")],
            },
            draw_top=card("yellow", "8"),
        )

        draw(state, "alice")

        self.assertEqual("bob", state["current_player"])
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            draw(state, "alice")
        self.assertEqual(before, state)


if __name__ == "__main__":
    unittest.main()
