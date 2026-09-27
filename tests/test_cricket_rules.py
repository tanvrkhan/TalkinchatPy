import copy
import unittest

from services import cricket


def player(name, uid):
    return {"user": name, "userid": str(uid), "key": f"uid:{uid}", "ai": False}


class CricketRulesTests(unittest.TestCase):
    def team(self, room, count=2):
        return {
            "room_id": room,
            "room_name": room.title(),
            "players": [player(f"{room}{i}", f"{room}-{i}") for i in range(count)],
        }

    def match(self, count=2, overs=1):
        return cricket.new_match("m1", self.team("alpha", count),
                                 self.team("beta", count), overs, seed=7)

    def start(self, state, batting="a"):
        state["toss"] = {"winner": batting, "decision": "bat"}
        return cricket.start_innings(state, batting)

    def ball(self, state, batter, bowler):
        current = state["innings"]["striker"]
        bowling = state["innings"]["bowler"]
        state = cricket.submit_choice(state, "bat", current, batter, state["revision"]).snapshot
        return cricket.submit_choice(state, "bowl", bowling, bowler, state["revision"])

    def test_new_match_validates_format_and_public_view_hides_secrets(self):
        with self.assertRaises(ValueError):
            cricket.new_match("bad", self.team("a", 4), self.team("b", 4), 3, 1)
        with self.assertRaises(ValueError):
            cricket.new_match("bad", self.team("a"), self.team("b"), 6, 1)
        state = self.match()
        self.assertEqual((2, 1), (state["team_size"], state["overs"]))
        self.assertNotIn("pending", cricket.public_view(state, "alpha"))

    def test_equal_numbers_are_wicket_and_mismatch_scores_batter_number(self):
        state = self.start(self.match(overs=2))
        result = self.ball(state, 4, 2)
        self.assertEqual((4, 0, 1), (result.snapshot["innings"]["runs"],
                                         result.snapshot["innings"]["wickets"],
                                         result.snapshot["innings"]["balls"]))
        result = self.ball(result.snapshot, 5, 5)
        self.assertEqual((4, 1, 2), (result.snapshot["innings"]["runs"],
                                         result.snapshot["innings"]["wickets"],
                                         result.snapshot["innings"]["balls"]))

    def test_odd_runs_and_over_end_swap_strike(self):
        state = self.start(self.match(overs=2))
        original = state["innings"]["striker"]
        state = self.ball(state, 3, 4).snapshot
        self.assertNotEqual(original, state["innings"]["striker"])
        for _ in range(5):
            state = self.ball(state, 2, 4).snapshot
        self.assertEqual(original, state["innings"]["striker"])
        self.assertEqual(6, state["innings"]["balls"])

    def test_completed_first_innings_starts_chase_and_target(self):
        state = self.start(self.match(count=1))
        state = self.ball(state, 4, 4).snapshot
        self.assertEqual(2, state["innings_number"])
        self.assertEqual(1, state["innings"]["target"])
        self.assertEqual("b", state["innings"]["batting"])

    def test_chase_ends_immediately_when_target_is_reached(self):
        state = self.start(self.match(count=1))
        state = self.ball(state, 2, 3).snapshot
        state = self.ball(state, 1, 1).snapshot
        self.assertEqual(2, state["innings_number"])
        result = self.ball(state, 3, 4)
        self.assertEqual("finished", result.snapshot["phase"])
        self.assertEqual("b", result.snapshot["winner"])

    def test_tie_enters_one_wicket_super_over(self):
        state = self.start(self.match(count=1))
        state = self.ball(state, 1, 1).snapshot
        state = self.ball(state, 2, 2).snapshot
        self.assertEqual("super_over", state["phase"])
        self.assertEqual(1, state["innings"]["max_wickets"])

    def test_choices_are_limited_to_one_through_six(self):
        state = self.start(self.match())
        with self.assertRaisesRegex(cricket.CricketError, "one through six"):
            cricket.submit_choice(
                state, "bat", state["innings"]["striker"], 0, state["revision"]
            )
        prompt = cricket.private_prompt(state, state["innings"]["striker"])
        self.assertEqual(["1", "2", "3", "4", "5", "6"],
                         [button["label"] for button in prompt["buttons"]])

    def test_stale_choice_never_mutates_state(self):
        state = self.start(self.match())
        before = copy.deepcopy(state)
        with self.assertRaises(cricket.StaleChoice):
            cricket.submit_choice(state, "bat", state["innings"]["striker"], 2,
                                   state["revision"] - 1)
        self.assertEqual(before, state)

    def test_ai_choice_is_deterministic_and_in_range(self):
        history = [{"batter": 6, "bowler": 2}, {"batter": 4, "bowler": 4}]
        self.assertEqual(cricket.ai_choice(history, 99), cricket.ai_choice(history, 99))
        self.assertIn(cricket.ai_choice(history, 99), range(1, 7))


if __name__ == "__main__":
    unittest.main()
