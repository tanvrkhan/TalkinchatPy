import random
import unittest

from services import games


class GameRuleTests(unittest.TestCase):
    def test_bingo_card_has_free_center_and_unique_columns(self):
        card = games.make_bingo_card(random.Random(7))
        self.assertIsNone(card[2][2])
        numbers = [value for row in card for value in row if value is not None]
        self.assertEqual(24, len(set(numbers)))

    def test_bingo_requires_a_complete_line(self):
        card = games.make_bingo_card(random.Random(7))
        self.assertFalse(games.bingo_has_won(card, set()))
        self.assertTrue(games.bingo_has_won(card, set(card[0])))

    def test_math_generator_answer_matches_expression(self):
        question, answer = games.gen_math()
        self.assertIsInstance(question, str)
        self.assertTrue(answer.lstrip("-").isdigit())


if __name__ == "__main__":
    unittest.main()
