"""Pure state transitions for the Thulla (Getaway) card game."""

import copy

from services.cards import card_to_dict, standard_deck


def new_game(players, rng):
    """Deal a new game and return JSON-safe private state."""
    players = list(players)
    if not 2 <= len(players) <= 8:
        raise ValueError("Thulla requires 2-8 players")
    if any(not isinstance(player, str) or not player for player in players):
        raise ValueError("players must have non-empty string IDs")
    if len(set(players)) != len(players):
        raise ValueError("players must be unique")

    deck = standard_deck()
    rng.shuffle(deck)
    waste_order = [card.id for card in deck]
    rng.shuffle(waste_order)

    hands = {player: [] for player in players}
    for index, dealt_card in enumerate(deck):
        hands[players[index % len(players)]].append(card_to_dict(dealt_card))

    ace_of_spades = next(
        dealt_card
        for dealt_card in deck
        if dealt_card.suit == "spades" and dealt_card.rank == "A"
    )
    opener = next(
        player
        for player in players
        if any(card["id"] == ace_of_spades.id for card in hands[player])
    )
    return {
        "game": "thulla",
        "phase": "playing",
        "players": players,
        "hands": hands,
        "current_player": opener,
        "trick": [],
        "first_trick": True,
        "waste": [],
        "waste_order": waste_order,
        "safe_players": [],
        "loser": None,
    }


def legal_card_ids(state, user):
    """Return the cards ``user`` may legally play in the current state."""
    if state.get("phase") != "playing" or state.get("current_player") != user:
        return set()
    hand = state.get("hands", {}).get(user)
    if not hand:
        return set()

    trick = state.get("trick", [])
    if state.get("first_trick") and not trick:
        return {
            card["id"]
            for card in hand
            if card["suit"] == "spades" and card["rank"] == "A"
        }
    if not trick:
        return {card["id"] for card in hand}

    led_suit = trick[0]["card"]["suit"]
    following = {card["id"] for card in hand if card["suit"] == led_suit}
    return following or {card["id"] for card in hand}


def play(state, user, card_id):
    """Validate and apply one card play, returning a JSON-safe public event."""
    next_state = copy.deepcopy(state)
    event = _play(next_state, user, card_id)
    state.clear()
    state.update(next_state)
    return event


def auto_play(state, user):
    """Play the lowest-ranked legal card for ``user``."""
    legal = legal_card_ids(state, user)
    if not legal:
        raise ValueError("user has no legal card to play")
    chosen = min(
        (card for card in state["hands"][user] if card["id"] in legal),
        key=lambda card: (card["value"], card["id"]),
    )
    event = play(state, user, chosen["id"])
    event["automatic"] = True
    return event


def public_view(state):
    """Project private state into the information visible to the room."""
    return {
        "game": "thulla",
        "phase": state["phase"],
        "players": list(state["players"]),
        "current_player": state["current_player"],
        "card_counts": {
            player: len(state["hands"][player]) for player in state["players"]
        },
        "trick": copy.deepcopy(state["trick"]),
        "first_trick": state["first_trick"],
        "waste_count": len(state["waste"]),
        "safe_players": list(state["safe_players"]),
        "loser": state["loser"],
    }


def _play(state, user, card_id):
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
    entry = {"player": user, "card": copy.deepcopy(played_card)}
    state["trick"].append(entry)

    event = {"kind": "play", "player": user, "card": copy.deepcopy(played_card)}
    active_players = _active_players(state)
    if state["first_trick"]:
        if len(state["trick"]) == len(active_players):
            return _discard_trick(state, event)
        state["current_player"] = _next_unplayed_player(state, user)
        return event

    led_suit = state["trick"][0]["card"]["suit"]
    if played_card["suit"] != led_suit:
        return _collect_thulla(state, event)
    if len(state["trick"]) == len(active_players):
        return _discard_trick(state, event)

    state["current_player"] = _next_unplayed_player(state, user)
    return event


def _active_players(state):
    safe = set(state["safe_players"])
    return [player for player in state["players"] if player not in safe]


def _next_unplayed_player(state, user):
    played = {entry["player"] for entry in state["trick"]}
    players = state["players"]
    start = players.index(user)
    for offset in range(1, len(players) + 1):
        candidate = players[(start + offset) % len(players)]
        if candidate not in state["safe_players"] and candidate not in played:
            return candidate
    raise ValueError("trick has no remaining player")


def _trick_winner(trick):
    led_suit = trick[0]["card"]["suit"]
    return max(
        (entry for entry in trick if entry["card"]["suit"] == led_suit),
        key=lambda entry: entry["card"]["value"],
    )["player"]


def _discard_trick(state, event):
    trick = state["trick"]
    leader = _trick_winner(trick)
    played_entries = copy.deepcopy(trick)

    all_active_empty = all(
        not state["hands"][player] for player in _active_players(state)
    )
    forced_draw = not all_active_empty and not state["hands"][leader]
    if forced_draw:
        state["hands"][leader].append(_draw_from_prior_waste(state))

    state["waste"].extend(entry["card"] for entry in trick)
    state["trick"] = []
    state["first_trick"] = False
    if all_active_empty:
        _finish_with_loser(state, leader)
    else:
        _mark_safe_empty_players(state, except_player=leader)
        state["current_player"] = leader
        _finish_if_one_player_remains(state)

    event.update(
        {
            "kind": "discard",
            "cards": played_entries,
            "leader": leader,
            "forced_draw": forced_draw,
            "finished": state["phase"] == "finished",
        }
    )
    return event


def _collect_thulla(state, event):
    trick = state["trick"]
    collector = _trick_winner(trick)
    played_entries = copy.deepcopy(trick)
    final_card_power_loss = (
        len(_active_players(state)) == 2
        and collector == trick[0]["player"]
        and not state["hands"][collector]
    )
    if final_card_power_loss:
        state["waste"].extend(entry["card"] for entry in trick)
        state["trick"] = []
        _finish_with_loser(state, collector)
    else:
        state["hands"][collector].extend(entry["card"] for entry in trick)
        state["trick"] = []
        _mark_safe_empty_players(state, except_player=collector)
        state["current_player"] = collector
        _finish_if_one_player_remains(state)

    event.update(
        {
            "kind": "thulla",
            "cards": played_entries,
            "collector": collector,
            "finished": state["phase"] == "finished",
        }
    )
    return event


def _draw_from_prior_waste(state):
    if not state["waste"]:
        raise ValueError("a power holder cannot draw from an empty waste pile")
    priority = {card_id: index for index, card_id in enumerate(state["waste_order"])}
    draw_index = min(
        range(len(state["waste"])),
        key=lambda index: priority[state["waste"][index]["id"]],
    )
    return state["waste"].pop(draw_index)


def _mark_safe_empty_players(state, except_player):
    for player in state["players"]:
        if (
            player != except_player
            and player not in state["safe_players"]
            and not state["hands"][player]
        ):
            state["safe_players"].append(player)


def _finish_with_loser(state, loser):
    for player in _active_players(state):
        if player != loser:
            state["safe_players"].append(player)
    state["phase"] = "finished"
    state["loser"] = loser
    state["current_player"] = None


def _finish_if_one_player_remains(state):
    remaining = [
        player
        for player in state["players"]
        if player not in state["safe_players"] and state["hands"][player]
    ]
    if len(remaining) == 1:
        state["phase"] = "finished"
        state["loser"] = remaining[0]
        state["current_player"] = None
