"""Shared immutable cards and deterministic decks for room card games."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Card:
    id: str
    suit: str
    rank: str
    value: int


_STANDARD_SUITS = ("clubs", "diamonds", "hearts", "spades")
_STANDARD_RANKS = (
    ("2", 2),
    ("3", 3),
    ("4", 4),
    ("5", 5),
    ("6", 6),
    ("7", 7),
    ("8", 8),
    ("9", 9),
    ("10", 10),
    ("J", 11),
    ("Q", 12),
    ("K", 13),
    ("A", 14),
)
_UNO_COLORS = ("red", "yellow", "green", "blue")
_UNO_ACTIONS = ("skip", "reverse", "draw2")


def standard_deck() -> list[Card]:
    """Return a fresh, deterministic 52-card standard deck."""
    deck = []
    for suit in _STANDARD_SUITS:
        for rank, value in _STANDARD_RANKS:
            deck.append(Card(f"c{len(deck) + 1}", suit, rank, value))
    return deck


def uno_deck() -> list[Card]:
    """Return a fresh, deterministic classic 108-card UNO deck."""
    deck = []
    for suit in _UNO_COLORS:
        deck.append(Card(f"u{len(deck) + 1}", suit, "0", 0))
        for rank in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            for _ in range(2):
                deck.append(Card(f"u{len(deck) + 1}", suit, rank, int(rank)))
        for rank in _UNO_ACTIONS:
            for _ in range(2):
                deck.append(Card(f"u{len(deck) + 1}", suit, rank, 20))

    for rank in ("wild", "wild4"):
        for _ in range(4):
            deck.append(Card(f"u{len(deck) + 1}", "wild", rank, 50))
    return deck


def card_to_dict(card: Card) -> dict:
    return {"id": card.id, "suit": card.suit, "rank": card.rank, "value": card.value}


def card_from_dict(data: dict) -> Card:
    return Card(
        id=data["id"],
        suit=data["suit"],
        rank=data["rank"],
        value=data["value"],
    )
