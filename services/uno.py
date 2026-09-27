"""Pure transactional state transitions for house-rule UNO."""

import copy
import random

from services.cards import card_to_dict, uno_deck


_COLORS = {"red", "yellow", "green", "blue"}
_COLOR_ORDER = ("red", "yellow", "green", "blue")


def new_match(players, rng, target=500):
    """Create a deterministic, JSON-safe UNO match."""
    players = list(players)
    if not 2 <= len(players) <= 10:
        raise ValueError("UNO requires 2-10 players")
    if any(not isinstance(player, str) or not player for player in players):
        raise ValueError("players must have non-empty string IDs")
    if len(set(players)) != len(players):
        raise ValueError("players must be unique")
    if isinstance(target, bool) or not isinstance(target, int) or target < 1:
        raise ValueError("target must be a positive integer")

    state = {
        "game": "uno",
        "phase": None,
        "players": players,
        "hands": {},
        "draw_pile": [],
        "discard_pile": [],
        "current_player": None,
        "direction": 1,
        "active_color": None,
        "pending_draw": 0,
        "pending_draw_type": None,
        "drawn_card_id": None,
        "color_chooser": None,
        "wild4_offender": None,
        "wild4_target": None,
        "wild4_had_active_color": None,
        "uno_window": None,
        "scores": {player: 0 for player in players},
        "target": target,
        "round_number": 1,
        "winner": None,
        "pending_round_candidates": [],
        "timeout_counts": {player: 0 for player in players},
        "removed_players": [],
        "shuffle_seed": rng.randrange(2**63),
        "shuffle_counter": 0,
    }
    _start_round(state)
    return state


def legal_card_ids(state, user):
    """Return card IDs that ``user`` may play in the current state."""
    if state.get("phase") != "playing" or state.get("current_player") != user:
        return set()
    hand = state.get("hands", {}).get(user)
    if not hand:
        return set()

    drawn_card_id = state.get("drawn_card_id")
    if drawn_card_id is not None:
        drawn = next((item for item in hand if item["id"] == drawn_card_id), None)
        if drawn is not None and _card_is_playable(state, drawn):
            return {drawn_card_id}
        return set()

    pending_type = state.get("pending_draw_type")
    if pending_type == "draw2":
        return {item["id"] for item in hand if item["rank"] == "draw2"}
    if pending_type == "wild4":
        return {
            item["id"]
            for item in hand
            if item["rank"] == "wild4"
        }
    return {
        item["id"] for item in hand if _card_is_playable(state, item)
    }


def play(state, user, card_id):
    """Validate and apply one card play."""
    next_state = copy.deepcopy(state)
    event = _play(next_state, user, card_id)
    _commit(state, next_state)
    return event


def draw(state, user):
    """Draw once, decline a playable draw, or take a pending penalty."""
    next_state = copy.deepcopy(state)
    event = _draw(next_state, user)
    _commit(state, next_state)
    return event


def choose_color(state, user, color):
    """Choose the active color after playing a Wild card."""
    next_state = copy.deepcopy(state)
    event = _choose_color(next_state, user, color)
    _commit(state, next_state)
    return event


def challenge_wild4(state, user):
    """Resolve a Wild Draw Four challenge from its targeted player."""
    next_state = copy.deepcopy(state)
    event = _challenge_wild4(next_state, user)
    _commit(state, next_state)
    return event


def call_uno(state, user):
    """Record a timely UNO call by the player with one card."""
    next_state = copy.deepcopy(state)
    window = next_state.get("uno_window")
    if not window or window.get("player") != user:
        raise ValueError("there is no UNO call window for this player")
    if len(next_state.get("hands", {}).get(user, [])) != 1:
        raise ValueError("UNO may be called only with one card")
    next_state["uno_window"] = None
    _commit(state, next_state)
    return {"kind": "uno", "player": user}


def catch_uno(state, user):
    """Catch another player's missed UNO call before the next action."""
    next_state = copy.deepcopy(state)
    if user not in next_state.get("players", []):
        raise ValueError("unknown player")
    window = next_state.get("uno_window")
    if not window:
        raise ValueError("there is no missed UNO call to catch")
    caught = window["player"]
    if caught == user:
        raise ValueError("a player cannot catch their own missed UNO call")
    if len(next_state.get("hands", {}).get(caught, [])) != 1:
        raise ValueError("the UNO catch window is stale")

    drawn = _draw_cards(next_state, caught, 2)
    next_state["uno_window"] = None
    _commit(state, next_state)
    return {"kind": "catch_uno", "player": user, "caught": caught, "count": drawn}


def auto_turn(state, user):
    """Resolve one timed-out turn and remove a third-timeout player when safe."""
    next_state = copy.deepcopy(state)
    if next_state.get("current_player") != user:
        raise ValueError("it is not this player's turn")
    if user not in next_state.get("hands", {}):
        raise ValueError("unknown player")
    if next_state.get("phase") not in {"playing", "choosing_color"}:
        raise ValueError("game has no turn to automate")

    prior_timeouts = next_state["timeout_counts"][user]
    if next_state["phase"] == "choosing_color":
        if next_state.get("color_chooser") != user:
            raise ValueError("only the Wild player may choose the color")
        event = _choose_color(next_state, user, _automatic_color(next_state, user))
    else:
        event = _auto_draw_and_pass(next_state, user)

    if next_state["phase"] != "finished" and user in next_state["timeout_counts"]:
        next_state["timeout_counts"][user] = prior_timeouts + 1
    event["automatic"] = True
    event["removed"] = _remove_after_third_timeout(next_state, user)
    _commit(state, next_state)
    return event


def public_view(state):
    """Project private UNO state into room-safe information."""
    challenge = None
    if state.get("wild4_target") is not None:
        challenge = {
            "offender": state["wild4_offender"],
            "target": state["wild4_target"],
        }
    return {
        "game": "uno",
        "phase": state["phase"],
        "players": list(state["players"]),
        "current_player": state["current_player"],
        "direction": state["direction"],
        "active_color": state["active_color"],
        "discard": copy.deepcopy(state["discard_pile"][-1]),
        "draw_count": len(state["draw_pile"]),
        "card_counts": {
            player: len(state["hands"][player]) for player in state["players"]
        },
        "pending_draw": state["pending_draw"],
        "pending_draw_type": state["pending_draw_type"],
        "color_chooser": state["color_chooser"],
        "challenge": challenge,
        "uno_catchable": (
            state["uno_window"]["player"] if state.get("uno_window") else None
        ),
        "scores": dict(state["scores"]),
        "target": state["target"],
        "round_number": state["round_number"],
        "winner": state["winner"],
        "removed_players": list(state["removed_players"]),
    }


def _play(state, user, card_id):
    if state.get("phase") != "playing":
        raise ValueError("game is not accepting card plays")
    if state.get("current_player") != user:
        raise ValueError("it is not this player's turn")
    hand = state.get("hands", {}).get(user)
    if hand is None:
        raise ValueError("unknown player")
    played_card = next((item for item in hand if item["id"] == card_id), None)
    if played_card is None:
        raise ValueError("card is not in the player's hand")
    if card_id not in legal_card_ids(state, user):
        raise ValueError("card is not legal in the current state")

    previous_active_color = state["active_color"]
    wild4_had_active_color = (
        played_card["rank"] == "wild4"
        and any(
            item["id"] != played_card["id"]
            and item["suit"] == previous_active_color
            for item in hand
        )
    )
    _begin_manual_action(state, user)
    hand.remove(played_card)
    state["discard_pile"].append(copy.deepcopy(played_card))
    state["drawn_card_id"] = None
    if len(hand) == 1:
        state["uno_window"] = {"player": user}
    if not hand and user not in state["pending_round_candidates"]:
        state["pending_round_candidates"].append(user)

    event = {
        "kind": "play",
        "player": user,
        "card": copy.deepcopy(played_card),
        "requires_color": False,
    }
    rank = played_card["rank"]
    if played_card["suit"] == "wild":
        state["active_color"] = None
        if rank == "wild" and _pending_round_winner(state) is not None:
            return _finish_round(state, event)
        state["phase"] = "choosing_color"
        state["color_chooser"] = user
        state["current_player"] = user
        event["requires_color"] = True
        if rank == "wild4":
            state["pending_draw"] += 4
            state["pending_draw_type"] = "wild4"
            state["wild4_offender"] = user
            state["wild4_target"] = None
            state["wild4_had_active_color"] = wild4_had_active_color
        return event

    state["active_color"] = played_card["suit"]
    if rank == "draw2":
        state["pending_draw"] += 2
        state["pending_draw_type"] = "draw2"
        state["current_player"] = _next_player(state, user)
        return event

    if rank == "reverse":
        state["direction"] *= -1
        if len(state["players"]) == 2:
            state["current_player"] = user
        else:
            state["current_player"] = _next_player(state, user)
    elif rank == "skip":
        state["current_player"] = _next_player(state, user, steps=2)
    else:
        state["current_player"] = _next_player(state, user)

    if _pending_round_winner(state) is not None:
        return _finish_round(state, event)
    return event


def _draw(state, user):
    if state.get("phase") != "playing":
        raise ValueError("game is not accepting draws")
    if state.get("current_player") != user:
        raise ValueError("it is not this player's turn")
    if user not in state.get("hands", {}):
        raise ValueError("unknown player")

    if state.get("drawn_card_id") is not None:
        _begin_manual_action(state, user)
        state["drawn_card_id"] = None
        state["current_player"] = _next_player(state, user)
        return {
            "kind": "draw",
            "player": user,
            "count": 0,
            "penalty": False,
            "playable": True,
            "passed": True,
        }

    pending = state.get("pending_draw", 0)
    if pending:
        _begin_manual_action(state, user)
        drawn = _draw_cards(state, user, pending)
        _clear_penalty(state)
        event = {
            "kind": "draw",
            "player": user,
            "count": drawn,
            "penalty": True,
            "playable": False,
            "passed": True,
        }
        if _pending_round_winner(state) is not None:
            return _finish_round(state, event)
        state["current_player"] = _next_player(state, user)
        return event

    _begin_manual_action(state, user)
    drawn = _draw_cards(state, user, 1)
    drawn_card = state["hands"][user][-1] if drawn else None
    playable = drawn_card is not None and _card_is_playable(state, drawn_card)
    event = {
        "kind": "draw",
        "player": user,
        "count": drawn,
        "penalty": False,
        "playable": playable,
        "passed": not playable,
    }
    if playable:
        state["drawn_card_id"] = drawn_card["id"]
    else:
        state["current_player"] = _next_player(state, user)
    return event


def _choose_color(state, user, color):
    if state.get("phase") != "choosing_color":
        raise ValueError("no Wild color is awaiting selection")
    if state.get("color_chooser") != user:
        raise ValueError("only the Wild player may choose the color")
    if color not in _COLORS:
        raise ValueError("invalid UNO color")

    state["timeout_counts"][user] = 0
    opening_wild = len(state["discard_pile"]) == 1
    rank = state["discard_pile"][-1]["rank"]
    state["phase"] = "playing"
    state["active_color"] = color
    state["color_chooser"] = None
    event = {"kind": "color", "player": user, "color": color}
    if rank == "wild4":
        target = _next_player(state, user)
        state["current_player"] = target
        state["wild4_target"] = target
        return event

    state["current_player"] = user if opening_wild else _next_player(state, user)
    if _pending_round_winner(state) is not None:
        return _finish_round(state, event)
    return event


def _challenge_wild4(state, user):
    if state.get("phase") != "playing":
        raise ValueError("game is not accepting a challenge")
    if state.get("current_player") != user or state.get("wild4_target") != user:
        raise ValueError("only the targeted player may challenge")
    if state.get("pending_draw_type") != "wild4" or not state.get("pending_draw"):
        raise ValueError("there is no Wild Draw Four to challenge")

    _begin_manual_action(state, user)
    offender = state["wild4_offender"]
    successful = state["wild4_had_active_color"] is True
    if successful:
        count = _draw_cards(state, offender, state["pending_draw"])
        drawn_by = offender
        _clear_penalty(state)
        state["current_player"] = user
    else:
        count = _draw_cards(state, user, state["pending_draw"] + 2)
        drawn_by = user
        _clear_penalty(state)
        state["current_player"] = _next_player(state, user)

    event = {
        "kind": "challenge",
        "player": user,
        "offender": offender,
        "successful": successful,
        "drawn_by": drawn_by,
        "count": count,
    }
    if _pending_round_winner(state) is not None:
        return _finish_round(state, event)
    return event


def _auto_draw_and_pass(state, user):
    state["uno_window"] = None
    pending = state.get("pending_draw", 0)
    if state.get("drawn_card_id") is not None:
        count = 0
        penalty = False
    elif pending:
        count = _draw_cards(state, user, pending)
        penalty = True
        _clear_penalty(state)
    else:
        count = _draw_cards(state, user, 1)
        penalty = False

    state["drawn_card_id"] = None
    event = {
        "kind": "draw",
        "player": user,
        "count": count,
        "penalty": penalty,
        "playable": False,
        "passed": True,
    }
    if _pending_round_winner(state) is not None:
        return _finish_round(state, event)
    state["current_player"] = _next_player(state, user)
    return event


def _automatic_color(state, user):
    counts = {
        color: sum(item["suit"] == color for item in state["hands"][user])
        for color in _COLOR_ORDER
    }
    return max(
        _COLOR_ORDER,
        key=lambda color: (counts[color], -_COLOR_ORDER.index(color)),
    )


def _remove_after_third_timeout(state, user):
    if user not in state.get("timeout_counts", {}):
        return False
    if state["timeout_counts"][user] < 3 or len(state["players"]) <= 2:
        return False
    if state.get("phase") == "finished" or state.get("pending_draw"):
        return False
    if user in state.get("pending_round_candidates", []):
        return False

    if state.get("current_player") == user:
        state["current_player"] = _next_player(state, user)
    returned = state["hands"].pop(user)
    state["draw_pile"].extend(returned)
    state["players"].remove(user)
    state["scores"].pop(user, None)
    state["timeout_counts"].pop(user, None)
    state["removed_players"].append(user)
    if (state.get("uno_window") or {}).get("player") == user:
        state["uno_window"] = None

    state["shuffle_counter"] += 1
    random.Random(
        f'uno:{state["shuffle_seed"]}:{state["round_number"]}:remove:'
        f'{state["shuffle_counter"]}'
    ).shuffle(state["draw_pile"])
    return True


def _card_is_playable(state, played_card):
    if played_card["suit"] == "wild":
        return True
    top = state["discard_pile"][-1]
    return (
        played_card["suit"] == state["active_color"]
        or played_card["rank"] == top["rank"]
    )


def _begin_manual_action(state, user):
    state["uno_window"] = None
    state["timeout_counts"][user] = 0


def _next_player(state, player, steps=1):
    players = state["players"]
    index = players.index(player)
    return players[(index + state["direction"] * steps) % len(players)]


def _draw_cards(state, player, count):
    drawn = 0
    for _ in range(count):
        if not state["draw_pile"]:
            _recycle_discard(state)
        if not state["draw_pile"]:
            break
        state["hands"][player].append(state["draw_pile"].pop())
        drawn += 1
    if drawn:
        state["pending_round_candidates"] = [
            candidate
            for candidate in state["pending_round_candidates"]
            if candidate != player
        ]
    return drawn


def _recycle_discard(state):
    if len(state["discard_pile"]) <= 1:
        return
    top = state["discard_pile"][-1]
    recycled = state["discard_pile"][:-1]
    state["shuffle_counter"] += 1
    random.Random(
        f'uno:{state["shuffle_seed"]}:{state["round_number"]}:recycle:'
        f'{state["shuffle_counter"]}'
    ).shuffle(recycled)
    state["draw_pile"] = recycled
    state["discard_pile"] = [top]


def _clear_penalty(state):
    state["pending_draw"] = 0
    state["pending_draw_type"] = None
    state["wild4_offender"] = None
    state["wild4_target"] = None
    state["wild4_had_active_color"] = None


def _pending_round_winner(state):
    candidates = [
        player
        for player in state["pending_round_candidates"]
        if player in state["hands"] and not state["hands"][player]
    ]
    state["pending_round_candidates"] = candidates
    return candidates[0] if candidates else None


def _finish_round(state, event):
    winner = _pending_round_winner(state)
    if winner is None:
        raise ValueError("round has no eligible winner")
    points = sum(
        item["value"]
        for player in state["players"]
        if player != winner
        for item in state["hands"][player]
    )
    state["scores"][winner] += points
    event.update(
        {
            "kind": "round",
            "round_winner": winner,
            "points": points,
            "match_winner": None,
        }
    )
    if state["scores"][winner] >= state["target"]:
        state["phase"] = "finished"
        state["winner"] = winner
        state["current_player"] = None
        state["uno_window"] = None
        state["drawn_card_id"] = None
        _clear_penalty(state)
        event["match_winner"] = winner
        return event

    state["round_number"] += 1
    _start_round(state)
    return event


def _start_round(state):
    deck = uno_deck()
    round_rng = random.Random(
        f'uno:{state["shuffle_seed"]}:round:{state["round_number"]}'
    )
    round_rng.shuffle(deck)
    shuffled = [card_to_dict(item) for item in deck]
    hands = {player: [] for player in state["players"]}
    for _ in range(7):
        for player in state["players"]:
            hands[player].append(shuffled.pop())

    upcard = shuffled.pop()
    while upcard["rank"] == "wild4":
        shuffled.append(upcard)
        round_rng.shuffle(shuffled)
        upcard = shuffled.pop()
    state.update(
        {
            "phase": "playing",
            "hands": hands,
            "draw_pile": shuffled,
            "discard_pile": [upcard],
            "current_player": state["players"][0],
            "direction": 1,
            "active_color": upcard["suit"],
            "pending_draw": 0,
            "pending_draw_type": None,
            "drawn_card_id": None,
            "color_chooser": None,
            "wild4_offender": None,
            "wild4_target": None,
            "wild4_had_active_color": None,
            "uno_window": None,
            "pending_round_candidates": [],
            "winner": None,
            "shuffle_counter": 0,
        }
    )
    for player in state["players"]:
        state["timeout_counts"][player] = 0

    first_player = state["players"][0]
    rank = upcard["rank"]
    if rank == "skip":
        state["current_player"] = _next_player(state, first_player)
    elif rank == "reverse":
        state["direction"] = -1
        state["current_player"] = _next_player(state, first_player)
    elif rank == "draw2":
        _draw_cards(state, first_player, 2)
        state["current_player"] = _next_player(state, first_player)
    elif rank == "wild":
        state["phase"] = "choosing_color"
        state["active_color"] = None
        state["color_chooser"] = first_player


def _commit(state, next_state):
    state.clear()
    state.update(next_state)
