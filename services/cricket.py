"""Pure deterministic rules for cross-room number cricket."""

import copy
import hashlib
import random
from dataclasses import dataclass


class CricketError(ValueError):
    pass


class StaleChoice(CricketError):
    pass


@dataclass(frozen=True)
class Transition:
    snapshot: dict
    events: tuple


def _validate_team(team):
    players = team.get("players") if isinstance(team, dict) else None
    if not isinstance(players, list) or not 1 <= len(players) <= 3:
        raise CricketError("Cricket teams require one to three players.")
    keys = [str(player.get("key", "")) for player in players]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise CricketError("Cricket players require unique stable keys.")


def new_match(match_id, team_a, team_b, overs, seed=None):
    _validate_team(team_a)
    _validate_team(team_b)
    if len(team_a["players"]) != len(team_b["players"]):
        raise CricketError("Cricket teams must be the same size.")
    if type(overs) is not int or not 1 <= overs <= 5:
        raise CricketError("Cricket overs must be between one and five.")
    rng = random.Random(seed)
    teams = {"a": copy.deepcopy(team_a), "b": copy.deepcopy(team_b)}
    for key, team in teams.items():
        team["key"] = key
    return {
        "schema": 1,
        "match_id": str(match_id),
        "phase": "toss",
        "revision": 1,
        "team_size": len(team_a["players"]),
        "overs": overs,
        "teams": teams,
        "toss": {"winner": rng.choice(("a", "b")), "decision": None},
        "innings_number": 0,
        "innings": None,
        "completed_innings": [],
        "pending_choices": {},
        "history": [],
        "winner": None,
        "result": None,
        "super_over_round": 0,
        "regulation_second": None,
    }


def choose_toss(state, team_key, decision):
    if state.get("phase") != "toss" or state["toss"]["winner"] != team_key:
        raise CricketError("Only the toss winner may choose.")
    if decision not in {"bat", "bowl"}:
        raise CricketError("Choose bat or bowl.")
    batting = team_key if decision == "bat" else _other(team_key)
    candidate = copy.deepcopy(state)
    candidate["toss"]["decision"] = decision
    candidate["revision"] += 1
    candidate = start_innings(candidate, batting)
    return Transition(candidate, ({"kind": "toss", "winner": team_key,
                                   "decision": decision},))


def _other(team_key):
    return "b" if team_key == "a" else "a"


def _new_innings(state, batting, *, target=None, max_balls=None, max_wickets=None):
    bowling = _other(batting)
    batting_players = state["teams"][batting]["players"]
    bowling_players = state["teams"][bowling]["players"]
    return {
        "batting": batting,
        "bowling": bowling,
        "runs": 0,
        "wickets": 0,
        "balls": 0,
        "max_balls": max_balls if max_balls is not None else state["overs"] * 6,
        "max_wickets": max_wickets if max_wickets is not None else len(batting_players),
        "target": target,
        "striker": batting_players[0]["key"],
        "non_striker": (batting_players[1]["key"] if len(batting_players) > 1
                         else batting_players[0]["key"]),
        "next_batter": 1,
        "dismissed": [],
        "bowler": bowling_players[0]["key"],
    }


def start_innings(state, batting):
    if batting not in state.get("teams", {}):
        raise CricketError("Unknown batting team.")
    candidate = copy.deepcopy(state)
    candidate["innings_number"] += 1
    candidate["phase"] = "active" if not candidate["super_over_round"] else "super_over"
    candidate["innings"] = _new_innings(candidate, batting)
    candidate["pending_choices"] = {}
    return candidate


def submit_choice(state, side, player_key, number, revision):
    if state.get("phase") not in {"active", "super_over"}:
        raise CricketError("No delivery is waiting for a choice.")
    if revision != state.get("revision"):
        raise StaleChoice("That cricket choice belongs to an older delivery.")
    if side not in {"bat", "bowl"} or type(number) is not int or not 1 <= number <= 6:
        raise CricketError("Choose a number from one through six.")
    innings = state["innings"]
    expected = innings["striker"] if side == "bat" else innings["bowler"]
    if str(player_key) != str(expected):
        raise CricketError("It is not that player's turn.")
    if side in state["pending_choices"]:
        raise CricketError("That choice is already locked.")
    candidate = copy.deepcopy(state)
    candidate["pending_choices"][side] = number
    candidate["revision"] += 1
    if len(candidate["pending_choices"]) < 2:
        return Transition(candidate, ({"kind": "choice_locked", "side": side},))
    return _resolve_delivery(candidate)


def _resolve_delivery(state):
    candidate = copy.deepcopy(state)
    innings = candidate["innings"]
    batter = candidate["pending_choices"]["bat"]
    bowler = candidate["pending_choices"]["bowl"]
    striker = innings["striker"]
    wicket = batter == bowler
    innings["balls"] += 1
    event = {
        "kind": "wicket" if wicket else "runs",
        "batter": batter,
        "bowler": bowler,
        "player": striker,
        "bowler_player": innings["bowler"],
    }
    if wicket:
        innings["wickets"] += 1
        innings["dismissed"].append(striker)
        _advance_after_wicket(candidate)
    else:
        innings["runs"] += batter
        event["runs"] = batter
        if batter % 2:
            _swap_strike(innings)
    candidate["history"].append(copy.deepcopy(event))
    candidate["pending_choices"] = {}

    ended = (innings["wickets"] >= innings["max_wickets"]
             or innings["balls"] >= innings["max_balls"]
             or (innings["target"] is not None and innings["runs"] >= innings["target"]))
    if ended:
        candidate, extra = _finish_innings(candidate)
        return Transition(candidate, tuple([event, *extra]))

    if innings["balls"] % 6 == 0:
        _swap_strike(innings)
        bowling = candidate["teams"][innings["bowling"]]["players"]
        innings["bowler"] = bowling[(innings["balls"] // 6) % len(bowling)]["key"]
        event["over_complete"] = True
    candidate["revision"] += 1
    return Transition(candidate, (event,))


def _swap_strike(innings):
    innings["striker"], innings["non_striker"] = (
        innings["non_striker"], innings["striker"]
    )


def _advance_after_wicket(state):
    innings = state["innings"]
    players = state["teams"][innings["batting"]]["players"]
    if innings["wickets"] >= innings["max_wickets"]:
        return
    next_index = innings["next_batter"] + 1
    if len(players) == 1:
        return
    if innings["next_batter"] == 1 and innings["non_striker"] == innings["striker"]:
        innings["non_striker"] = players[1]["key"]
    if next_index < len(players):
        innings["striker"] = players[next_index]["key"]
        innings["next_batter"] = next_index
    else:
        alive = [p["key"] for p in players if p["key"] not in innings["dismissed"]]
        if alive:
            innings["striker"] = alive[0]
            innings["non_striker"] = alive[-1]


def _finish_innings(state):
    innings = copy.deepcopy(state["innings"])
    state["completed_innings"].append(innings)
    batting = innings["batting"]
    events = [{"kind": "innings_complete", "team": batting,
               "runs": innings["runs"], "wickets": innings["wickets"]}]
    if state["super_over_round"]:
        return _finish_super_over_innings(state, events)
    if state["innings_number"] == 1:
        state["regulation_second"] = _other(batting)
        state["innings_number"] = 1
        state["innings"] = _new_innings(
            state, _other(batting), target=innings["runs"] + 1
        )
        state["innings_number"] = 2
        state["pending_choices"] = {}
        state["revision"] += 1
        events.append({"kind": "chase_started", "target": innings["runs"] + 1})
        return state, events

    first = state["completed_innings"][-2]
    second = state["completed_innings"][-1]
    if second["runs"] > first["runs"]:
        return _finish_match(state, second["batting"], events)
    if second["runs"] < first["runs"]:
        return _finish_match(state, first["batting"], events)
    return _start_super_over(state, events)


def _start_super_over(state, events):
    state["super_over_round"] += 1
    first_batting = state["regulation_second"]
    if state["super_over_round"] % 2 == 0:
        first_batting = _other(first_batting)
    state["phase"] = "super_over"
    state["innings_number"] = 1
    state["innings"] = _new_innings(state, first_batting, max_balls=6, max_wickets=1)
    state["pending_choices"] = {}
    state["revision"] += 1
    events.append({"kind": "super_over_started", "round": state["super_over_round"]})
    return state, events


def _finish_super_over_innings(state, events):
    current = state["innings"]
    if state["innings_number"] == 1:
        state["innings_number"] = 2
        state["innings"] = _new_innings(
            state, _other(current["batting"]), target=current["runs"] + 1,
            max_balls=6, max_wickets=1,
        )
        state["pending_choices"] = {}
        state["revision"] += 1
        return state, events
    first, second = state["completed_innings"][-2:]
    if first["runs"] == second["runs"]:
        return _start_super_over(state, events)
    winner = first["batting"] if first["runs"] > second["runs"] else second["batting"]
    return _finish_match(state, winner, events)


def _finish_match(state, winner, events):
    state["phase"] = "finished"
    state["winner"] = winner
    state["result"] = {"winner": winner, "super_over": state["super_over_round"]}
    state["pending_choices"] = {}
    state["revision"] += 1
    events.append({"kind": "match_complete", "winner": winner})
    return state, events


def public_view(state, room_id=None):
    innings = state.get("innings") or {}
    return {
        "match_id": state["match_id"],
        "phase": state["phase"],
        "revision": state["revision"],
        "teams": copy.deepcopy(state["teams"]),
        "overs": state["overs"],
        "innings_number": state["innings_number"],
        "score": {key: innings.get(key) for key in (
            "batting", "runs", "wickets", "balls", "max_balls", "target",
            "striker", "bowler"
        )},
        "winner": state.get("winner"),
        "super_over_round": state.get("super_over_round", 0),
        "recent": copy.deepcopy(state.get("history", [])[-6:]),
        "viewer_room": str(room_id) if room_id is not None else None,
    }


def private_prompt(state, player_key, prefix=","):
    innings = state.get("innings") or {}
    role = ("bat" if innings.get("striker") == player_key else
            "bowl" if innings.get("bowler") == player_key else None)
    if role is None:
        raise CricketError("That player has no pending cricket choice.")
    return {
        "role": role,
        "revision": state["revision"],
        "buttons": [
            {"label": str(number),
             "message": f"{prefix}cricket choose {role} {number} {state['revision']}"}
            for number in range(1, 7)
        ],
    }


def ai_choice(revealed_history, seed):
    encoded = repr((revealed_history, seed)).encode("utf-8")
    return 1 + int.from_bytes(hashlib.sha256(encoded).digest()[:4], "big") % 6
