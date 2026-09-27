"""Pure state transitions for Rang (Court Piece)."""

import copy
import random

from services.cards import card_to_dict, standard_deck


_SUITS = {"clubs", "diamonds", "hearts", "spades"}


def new_game(players, rng, court_target=1):
    """Create a JSON-safe Rang session after the opening five-card deal."""
    players = list(players)
    if len(players) != 4:
        raise ValueError("Rang requires exactly four players")
    if any(not isinstance(player, str) or not player for player in players):
        raise ValueError("players must have non-empty string IDs")
    if len(set(players)) != len(players):
        raise ValueError("players must be unique")
    if (
        isinstance(court_target, bool)
        or not isinstance(court_target, int)
        or court_target < 1
    ):
        raise ValueError("court_target must be a positive integer")

    shuffle_seed = rng.randrange(2**63)
    dealer = players[rng.randrange(len(players))]
    state = {
        "game": "rang",
        "phase": None,
        "players": players,
        "teams": [[players[0], players[2]], [players[1], players[3]]],
        "dealer": dealer,
        "trump_caller": None,
        "trump": None,
        "hands": {player: [] for player in players},
        "stock": [],
        "current_player": None,
        "trick": [],
        "team_tricks": [0, 0],
        "deal_streaks": [0, 0],
        "courts": [0, 0],
        "court_target": court_target,
        "deal_number": 1,
        "winner_team": None,
        "timeout_counts": {player: 0 for player in players},
        "paused_player": None,
        "paused_phase": None,
        "shuffle_seed": shuffle_seed,
    }
    _start_deal(state, dealer)
    return state


def choose_trump(state, user, suit):
    """Choose trumps as the caller and finish dealing the current deal."""
    next_state = copy.deepcopy(state)
    event = _choose_trump(next_state, user, suit)
    state.clear()
    state.update(next_state)
    return event


def legal_card_ids(state, user):
    """Return the cards ``user`` may legally play on the current turn."""
    if state.get("phase") != "playing" or state.get("current_player") != user:
        return set()
    hand = state.get("hands", {}).get(user)
    if not hand:
        return set()
    trick = state.get("trick", [])
    if not trick:
        return {card["id"] for card in hand}

    led_suit = trick[0]["card"]["suit"]
    following = {card["id"] for card in hand if card["suit"] == led_suit}
    return following or {card["id"] for card in hand}


def play(state, user, card_id):
    """Validate and apply one card play, returning a JSON-safe public event."""
    next_state = copy.deepcopy(state)
    event = _play(next_state, user, card_id, automatic=False)
    state.clear()
    state.update(next_state)
    return event


def auto_play(state, user):
    """Play the lowest legal card and pause after the user's third timeout."""
    next_state = copy.deepcopy(state)
    legal = legal_card_ids(next_state, user)
    if not legal:
        raise ValueError("user has no legal card to play")
    chosen = min(
        (card for card in next_state["hands"][user] if card["id"] in legal),
        key=lambda card: (card["value"], card["id"]),
    )
    prior_timeouts = next_state["timeout_counts"][user]
    event = _play(next_state, user, chosen["id"], automatic=True)
    next_state["timeout_counts"][user] = prior_timeouts + 1
    event["automatic"] = True
    event["paused"] = False

    if next_state["phase"] != "finished" and prior_timeouts + 1 >= 3:
        next_state["paused_phase"] = next_state["phase"]
        next_state["paused_player"] = user
        next_state["phase"] = "paused"
        event["paused"] = True

    state.clear()
    state.update(next_state)
    return event


def resume(state, user):
    """Resume a paused session when its absent participant returns."""
    next_state = copy.deepcopy(state)
    if next_state.get("phase") != "paused":
        raise ValueError("game is not paused")
    if next_state.get("paused_player") != user:
        raise ValueError("only the absent player can resume")

    next_state["phase"] = next_state["paused_phase"]
    next_state["paused_phase"] = None
    next_state["paused_player"] = None
    next_state["timeout_counts"][user] = 0
    state.clear()
    state.update(next_state)
    return {"kind": "resume", "player": user}


def public_view(state):
    """Project private Rang state into information visible to the room."""
    return {
        "game": "rang",
        "phase": state["phase"],
        "players": list(state["players"]),
        "teams": copy.deepcopy(state["teams"]),
        "dealer": state["dealer"],
        "trump_caller": state["trump_caller"],
        "trump": state["trump"],
        "current_player": state["current_player"],
        "card_counts": {
            player: len(state["hands"][player]) for player in state["players"]
        },
        "trick": copy.deepcopy(state["trick"]),
        "team_tricks": list(state["team_tricks"]),
        "deal_streaks": list(state["deal_streaks"]),
        "courts": list(state["courts"]),
        "court_target": state["court_target"],
        "deal_number": state["deal_number"],
        "winner_team": state["winner_team"],
        "paused_player": state["paused_player"],
    }


def _choose_trump(state, user, suit):
    if state.get("phase") != "choosing_trump":
        raise ValueError("game is not choosing trump")
    if state.get("trump_caller") != user:
        raise ValueError("only the trump caller can choose trump")
    if suit not in _SUITS:
        raise ValueError("invalid trump suit")

    order = _deal_order(state, state["dealer"])
    for _ in range(2):
        for player in order:
            state["hands"][player].extend(state["stock"][:4])
            del state["stock"][:4]
    state["trump"] = suit
    state["phase"] = "playing"
    state["current_player"] = user
    return {"kind": "trump", "player": user, "trump": suit}


def _play(state, user, card_id, *, automatic):
    if state.get("phase") != "playing":
        raise ValueError("game is not active")
    if state.get("current_player") != user:
        raise ValueError("it is not this player's turn")

    hand = state.get("hands", {}).get(user)
    if hand is None:
        raise ValueError("unknown player")
    played_card = next((card for card in hand if card["id"] == card_id), None)
    if played_card is None:
        raise ValueError("card is not in the player's hand")
    if card_id not in legal_card_ids(state, user):
        raise ValueError("card does not follow the led suit")

    hand.remove(played_card)
    state["trick"].append({"player": user, "card": copy.deepcopy(played_card)})
    if not automatic:
        state["timeout_counts"][user] = 0
    event = {"kind": "play", "player": user, "card": copy.deepcopy(played_card)}

    if len(state["trick"]) < 4:
        state["current_player"] = _right_of(state, user)
        return event
    return _finish_trick(state, event)


def _finish_trick(state, event):
    entries = copy.deepcopy(state["trick"])
    winner = _trick_winner(state["trick"], state["trump"])
    winning_team = _team_index(state, winner)
    state["team_tricks"][winning_team] += 1
    state["trick"] = []
    state["current_player"] = winner
    event.update(
        {
            "kind": "trick",
            "cards": entries,
            "winner": winner,
            "winning_team": winning_team + 1,
        }
    )

    if state["team_tricks"][winning_team] == 7:
        _finish_deal(state, winning_team, event)
    return event


def _finish_deal(state, winning_team, event):
    losing_team = 1 - winning_team
    court = state["team_tricks"][losing_team] == 0
    if court:
        state["deal_streaks"] = [0, 0]
    else:
        state["deal_streaks"][winning_team] += 1
        state["deal_streaks"][losing_team] = 0
        if state["deal_streaks"][winning_team] == 7:
            court = True
            state["deal_streaks"] = [0, 0]

    if court:
        state["courts"][winning_team] += 1

    event.update(
        {
            "deal_winner": winning_team + 1,
            "court": court,
            "court_winner": winning_team + 1 if court else None,
            "finished": False,
        }
    )
    if state["courts"][winning_team] >= state["court_target"]:
        state["phase"] = "finished"
        state["current_player"] = None
        state["winner_team"] = winning_team + 1
        event["finished"] = True
        return

    dealer_team = _team_index(state, state["dealer"])
    caller_team = _team_index(state, state["trump_caller"])
    if winning_team == dealer_team:
        next_dealer = _right_of(state, state["dealer"])
    elif winning_team == caller_team and court:
        next_dealer = _partner_of(state, state["dealer"])
    else:
        next_dealer = state["dealer"]

    state["deal_number"] += 1
    _start_deal(state, next_dealer)


def _start_deal(state, dealer):
    deck = standard_deck()
    random.Random(f'{state["shuffle_seed"]}:{state["deal_number"]}').shuffle(deck)
    dealt = [card_to_dict(card) for card in deck]
    order = _deal_order(state, dealer)
    hands = {player: [] for player in state["players"]}
    offset = 0
    for player in order:
        hands[player].extend(dealt[offset : offset + 5])
        offset += 5

    state["phase"] = "choosing_trump"
    state["dealer"] = dealer
    state["trump_caller"] = order[0]
    state["trump"] = None
    state["hands"] = hands
    state["stock"] = dealt[offset:]
    state["current_player"] = order[0]
    state["trick"] = []
    state["team_tricks"] = [0, 0]
    state["paused_player"] = None
    state["paused_phase"] = None


def _trick_winner(trick, trump):
    trump_cards = [entry for entry in trick if entry["card"]["suit"] == trump]
    candidates = trump_cards or [
        entry for entry in trick if entry["card"]["suit"] == trick[0]["card"]["suit"]
    ]
    return max(candidates, key=lambda entry: entry["card"]["value"])["player"]


def _deal_order(state, dealer):
    players = state["players"]
    start = (players.index(dealer) + 1) % len(players)
    return [players[(start + offset) % len(players)] for offset in range(len(players))]


def _right_of(state, player):
    players = state["players"]
    return players[(players.index(player) + 1) % len(players)]


def _partner_of(state, player):
    players = state["players"]
    return players[(players.index(player) + 2) % len(players)]


def _team_index(state, player):
    for index, team in enumerate(state["teams"]):
        if player in team:
            return index
    raise ValueError("unknown player")
