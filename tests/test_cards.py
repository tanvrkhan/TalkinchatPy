import unittest
from dataclasses import FrozenInstanceError

from services.cards import Card, card_from_dict, card_to_dict, standard_deck, uno_deck


class CardModelTests(unittest.TestCase):
    def test_card_is_immutable_and_serializes_to_the_shared_shape(self):
        card = Card("c17", "spades", "A", 14)

        self.assertEqual(
            {"id": "c17", "suit": "spades", "rank": "A", "value": 14},
            card_to_dict(card),
        )
        self.assertEqual(card, card_from_dict(card_to_dict(card)))
        with self.assertRaises(FrozenInstanceError):
            card.rank = "K"

    def test_standard_deck_has_52_stable_unique_cards(self):
        deck = standard_deck()

        self.assertEqual(52, len(deck))
        self.assertEqual(52, len({card.id for card in deck}))
        self.assertEqual(
            "A", [card.rank for card in deck if card.suit == "spades"][-1]
        )
        self.assertEqual(deck, standard_deck())
        self.assertEqual(
            {"clubs", "diamonds", "hearts", "spades"},
            {card.suit for card in deck},
        )
        self.assertEqual(
            ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"],
            [card.rank for card in deck if card.suit == "hearts"],
        )
        self.assertEqual([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                         [card.value for card in deck if card.suit == "hearts"])
        self.assertEqual([f"c{index}" for index in range(1, 53)],
                         [card.id for card in deck])

    def test_uno_deck_has_108_cards_with_expected_action_counts(self):
        deck = uno_deck()

        self.assertEqual(108, len(deck))
        self.assertEqual(4, sum(card.rank == "wild4" for card in deck))
        self.assertEqual(deck[0], card_from_dict(card_to_dict(deck[0])))
        self.assertEqual(4, sum(card.rank == "0" for card in deck))
        self.assertEqual(8, sum(card.rank == "skip" for card in deck))
        self.assertEqual(8, sum(card.rank == "reverse" for card in deck))
        self.assertEqual(8, sum(card.rank == "draw2" for card in deck))
        self.assertEqual(4, sum(card.rank == "wild" for card in deck))
        self.assertEqual({"red", "yellow", "green", "blue", "wild"},
                         {card.suit for card in deck})
        self.assertEqual([f"u{index}" for index in range(1, 109)],
                         [card.id for card in deck])


if __name__ == "__main__":
    unittest.main()
