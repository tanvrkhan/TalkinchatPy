"""Persistent orchestration for room card-game sessions.

Pure game rules stay in their game modules.  This layer owns identity, lobbies,
optimistic versions, opaque actions, durable deadlines, and reward claims.
"""

import asyncio
import copy
import inspect
import math
import random
import re
import secrets
import time

from services import rang, thulla, uno
from services.cards import card_to_dict, standard_deck, uno_deck


SNAPSHOT_VERSION = 1
LOBBY_SECONDS = 60
TURN_SECONDS = 120
HAND_PAGE_SIZE = 16
BINGO_STORE_PREFIX = "bingo:"

_GAME_LIMITS = {
    "thulla": (2, 8),
    "rang": (4, 4),
    "uno": (2, 10),
}
_SUITS = ("hearts", "diamonds", "clubs", "spades")
_COLORS = ("red", "yellow", "green", "blue")
_ACTION_ID_RE = re.compile(r"card_[1-9][0-9]*_[A-Za-z0-9_-]{16}\Z")
_STANDARD_CARDS = {card.id: card_to_dict(card) for card in standard_deck()}
_UNO_CARDS = {card.id: card_to_dict(card) for card in uno_deck()}
_THULLA_STATE_FIELDS = frozenset({
    "game", "phase", "players", "hands", "current_player", "trick",
    "first_trick", "waste", "waste_order", "safe_players", "loser",
})
_RANG_STATE_FIELDS = frozenset({
    "game", "phase", "players", "teams", "dealer", "trump_caller", "trump",
    "hands", "stock", "current_player", "trick", "team_tricks",
    "deal_streaks", "courts", "court_target", "deal_number", "winner_team",
    "timeout_counts", "paused_player", "paused_phase", "shuffle_seed",
})
_UNO_STATE_FIELDS = frozenset({
    "game", "phase", "players", "hands", "draw_pile", "discard_pile",
    "current_player", "direction", "active_color", "pending_draw",
    "pending_draw_type", "drawn_card_id", "color_chooser", "wild4_offender",
    "wild4_target", "wild4_had_active_color", "uno_window", "scores", "target",
    "round_number", "winner", "pending_round_candidates", "timeout_counts",
    "removed_players", "shuffle_seed", "shuffle_counter",
})


def _thulla_settlement(state, players):
    winner_keys = list(state["safe_players"])
    return winner_keys, {
        "game": "thulla",
        "safe_players": [players[key]["user"] for key in winner_keys],
        "loser": players[state["loser"]]["user"],
    }


def _rang_settlement(state, players):
    team_number = int(state["winner_team"])
    winner_keys = list(state["teams"][team_number - 1])
    return winner_keys, {
        "game": "rang",
        "winner_team": team_number,
        "winners": [players[key]["user"] for key in winner_keys],
    }


def _uno_settlement(state, players):
    winner_keys = [state["winner"]]
    return winner_keys, {
        "game": "uno", "winner": players[winner_keys[0]]["user"],
    }


_GAME_ADAPTERS = {
    "thulla": {
        "new": thulla.new_game, "public": thulla.public_view,
        "legal": thulla.legal_card_ids, "play": thulla.play,
        "auto": thulla.auto_play, "settlement": _thulla_settlement,
    },
    "rang": {
        "new": rang.new_game, "public": rang.public_view,
        "legal": rang.legal_card_ids, "play": rang.play,
        "auto": rang.auto_play, "settlement": _rang_settlement,
    },
    "uno": {
        "new": uno.new_match, "public": uno.public_view,
        "legal": uno.legal_card_ids, "play": uno.play,
        "auto": uno.auto_turn, "settlement": _uno_settlement,
    },
}


class SessionError(ValueError):
    """A card-session request was invalid and made no state change."""


class SessionConflict(SessionError):
    """A room already has a different card game."""


class StaleAction(SessionError):
    """An action was issued for an older snapshot version."""


class CardSessionManager:
    """Coordinate persistent card sessions without knowing chat transport."""

    def __init__(
        self,
        store,
        *,
        now=time.time,
        rng_factory=random.Random,
        sleep=asyncio.sleep,
        schedule_tasks=True,
        on_lobby_started=None,
        on_lobby_expired=None,
        on_timeout=None,
    ):
        self.store = store
        self._now = now
        self._rng_factory = rng_factory
        self._sleep = sleep
        self._schedule_tasks = bool(schedule_tasks)
        self.on_lobby_started = on_lobby_started
        self.on_lobby_expired = on_lobby_expired
        self.on_timeout = on_timeout
        self._sessions = {}
        self._locks = {}
        self._tasks = {}

    @staticmethod
    def is_action_id(value):
        return isinstance(value, str) and _ACTION_ID_RE.fullmatch(value) is not None

    def get(self, room_id):
        session = self._sessions.get(self._room_key(room_id))
        return copy.deepcopy(session) if session is not None else None

    def has_session(self, room_id, game=None, phases=None):
        session = self._sessions.get(self._room_key(room_id))
        if session is None:
            return False
        if game is not None and session["game"] != game:
            return False
        return phases is None or session["phase"] in set(phases)

    def find_for_player(self, user, userid, *, game=None, phases=None):
        matches = []
        for session in self._sessions.values():
            if game is not None and session["game"] != game:
                continue
            if phases is not None and session["phase"] not in set(phases):
                continue
            try:
                self._participant(session, user, userid)
            except SessionError:
                continue
            matches.append(copy.deepcopy(session))
        if len(matches) > 1:
            raise SessionError("You are in more than one matching card session; use the room command.")
        return matches[0] if matches else None

    async def join_or_create(self, room_id, game, user, userid):
        game = str(game).lower()
        if game not in _GAME_LIMITS:
            raise SessionError("Unknown card game.")
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._sessions.get(key)
            if current is not None and current["phase"] == "finished":
                if not self._settlement_complete(current):
                    raise SessionConflict("The previous card result is still being recorded.")
                current = None

            if current is None:
                player = self._new_participant(user, userid)
                now = float(self._now())
                candidate = {
                    "schema_version": SNAPSHOT_VERSION,
                    "session_id": secrets.token_urlsafe(12),
                    "room_id": room_id,
                    "game": game,
                    "phase": "lobby",
                    "creator_key": player["key"],
                    "players": [player],
                    "created_at": now,
                    "lobby_deadline": now + LOBBY_SECONDS,
                    "turn_deadline": None,
                    "delivery_deadline": None,
                    "version": 1,
                    "state": None,
                    "actions": {},
                    "automatic_turns": {player["key"]: 0},
                    "pause_reason": None,
                    "paused_player": None,
                    "pending_delivery": [],
                    "result": None,
                    "settlement": None,
                }
                self._save(key, candidate)
                self._sessions[key] = candidate
                kind = "created"
            else:
                if current["game"] != game:
                    raise SessionConflict(
                        f"{current['game'].title()} already owns this room's card table."
                    )
                if current["phase"] != "lobby":
                    raise SessionConflict(f"{game.title()} is already in progress in this room.")
                try:
                    self._participant(current, user, userid)
                except SessionError:
                    pass
                else:
                    return self._transition(current, {"kind": "already_joined"})
                maximum = _GAME_LIMITS[game][1]
                if len(current["players"]) >= maximum:
                    raise SessionError(f"{game.title()} already has its maximum {maximum} players.")
                candidate = copy.deepcopy(current)
                player = self._new_participant(user, userid)
                candidate["players"].append(player)
                candidate["automatic_turns"][player["key"]] = 0
                candidate["version"] += 1
                self._save(key, candidate)
                self._sessions[key] = candidate
                kind = "joined"

        if self._schedule_tasks:
            self.arm_lobby_timer(room_id)
        return self._transition(candidate, {"kind": kind, "player": user})

    async def start(
        self,
        room_id,
        user,
        userid,
        *,
        is_admin=False,
        expected_version=None,
        gate_delivery=False,
    ):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            self._check_version(current, expected_version)
            if current["phase"] != "lobby":
                raise SessionError("This card lobby has already started.")
            if is_admin:
                actor = self._new_participant(user, userid)
            else:
                actor = self._participant(current, user, userid)
                if actor["key"] != current["creator_key"]:
                    raise SessionError(
                        "Only the lobby creator or a room/bot admin can start early."
                    )
            minimum, maximum = _GAME_LIMITS[current["game"]]
            count = len(current["players"])
            if not minimum <= count <= maximum:
                required = str(minimum) if minimum == maximum else f"{minimum}-{maximum}"
                raise SessionError(
                    f"{current['game'].title()} needs {required} players; this lobby has {count}."
                )

            candidate = copy.deepcopy(current)
            player_keys = [player["key"] for player in candidate["players"]]
            rng = self._rng_factory()
            state = _GAME_ADAPTERS[candidate["game"]]["new"](player_keys, rng)
            candidate.update(
                {
                    "phase": "delivering" if gate_delivery else "active",
                    "state": state,
                    "lobby_deadline": None,
                    "turn_deadline": (
                        None if gate_delivery else float(self._now()) + TURN_SECONDS
                    ),
                    "delivery_deadline": (
                        float(self._now()) + TURN_SECONDS if gate_delivery else None
                    ),
                    "actions": {},
                    "pause_reason": "delivery" if gate_delivery else None,
                    "paused_player": (
                        state.get("current_player") if gate_delivery else None
                    ),
                    "pending_delivery": player_keys if gate_delivery else [],
                    "version": candidate["version"] + 1,
                }
            )
            self._save(key, candidate)
            self._sessions[key] = candidate
        self._cancel_task(key)
        return self._transition(candidate, {"kind": "started"})

    async def private_hand(
        self,
        room_id,
        user,
        userid,
        *,
        page=1,
        prefix=",",
        allow_actions=True,
    ):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            player = self._participant(current, user, userid)
            state = current.get("state") or {}
            hand = list((state.get("hands") or {}).get(player["key"], []))
            if current["phase"] == "lobby" or "hands" not in state:
                raise SessionError("This card game has not dealt hands yet.")
            pages = max(1, math.ceil(len(hand) / HAND_PAGE_SIZE))
            try:
                page = int(page)
            except (TypeError, ValueError):
                page = 1
            page = max(1, min(page, pages))
            start = (page - 1) * HAND_PAGE_SIZE
            shown = copy.deepcopy(hand[start:start + HAND_PAGE_SIZE])

            candidate = copy.deepcopy(current)
            candidate["actions"] = {
                action_id: action
                for action_id, action in candidate.get("actions", {}).items()
                if action.get("player") != player["key"]
            }
            buttons = []
            if allow_actions and candidate["phase"] in {"active", "delivering"}:
                legal = self._legal_card_ids(candidate, player["key"])
                for card in shown:
                    if card["id"] not in legal:
                        continue
                    action_id = self._new_action_id(candidate["version"])
                    candidate["actions"][action_id] = {
                        "version": candidate["version"],
                        "room": key,
                        "player": player["key"],
                        "kind": "play",
                        "card_id": card["id"],
                    }
                    buttons.append(
                        {"label": self._card_label(card), "message": f"{prefix}play {action_id}"}
                    )
                buttons.extend(self._state_action_buttons(candidate, player["key"], prefix))
            elif allow_actions and candidate["phase"] == "paused":
                if candidate.get("paused_player") == player["key"]:
                    buttons.append(
                        {"label": "Resume", "message": f"{prefix}resume {candidate['version']}"}
                    )

            if page > 1:
                buttons.append({"label": "Previous", "message": f"{prefix}hand {page - 1}"})
            if page < pages:
                buttons.append({"label": "Next", "message": f"{prefix}hand {page + 1}"})

            self._save(key, candidate)
            self._sessions[key] = candidate
            return {
                "room_id": candidate["room_id"],
                "game": candidate["game"],
                "player": copy.deepcopy(player),
                "cards": shown,
                "page": page,
                "pages": pages,
                "buttons": buttons,
                "version": candidate["version"],
            }

    async def play(self, room_id, user, userid, action_id):
        key = self._room_for_action(room_id, action_id)
        async with self._lock(key):
            current = self._require_session(key)
            action = current.get("actions", {}).get(action_id)
            if action is None:
                self._raise_unknown_action(current, action_id)
            if action.get("room") != key:
                raise SessionError("That card action belongs to another room.")
            player = self._participant(current, user, userid)
            if action.get("player") != player["key"]:
                raise SessionError("That card action belongs to another player.")
            self._check_version(current, action.get("version"))
            if action.get("kind") != "play":
                raise SessionError("That is not a card-play action.")
            return self._manual_transition_locked(
                key,
                current,
                player,
                lambda state: self._rules_play(
                    current["game"], state, player["key"], action["card_id"]
                ),
            )

    async def draw(self, room_id, user, userid, *, expected_version=None):
        return await self._direct_transition(
            room_id,
            user,
            userid,
            game="uno",
            expected_version=expected_version,
            mutate=lambda _session, state, player: uno.draw(state, player["key"]),
        )

    async def choose_trump(self, room_id, user, userid, suit, *, expected_version=None):
        return await self._direct_transition(
            room_id,
            user,
            userid,
            game="rang",
            expected_version=expected_version,
            mutate=lambda _session, state, player: rang.choose_trump(
                state, player["key"], str(suit).lower()
            ),
        )

    async def choose_color(self, room_id, user, userid, color, *, expected_version=None):
        return await self._direct_transition(
            room_id,
            user,
            userid,
            game="uno",
            expected_version=expected_version,
            mutate=lambda _session, state, player: uno.choose_color(
                state, player["key"], str(color).lower()
            ),
        )

    async def challenge(self, room_id, user, userid, *, expected_version=None):
        return await self._direct_transition(
            room_id,
            user,
            userid,
            game="uno",
            expected_version=expected_version,
            mutate=lambda _session, state, player: uno.challenge_wild4(
                state, player["key"]
            ),
        )

    async def call_uno(self, room_id, user, userid, *, expected_version=None):
        return await self._direct_transition(
            room_id,
            user,
            userid,
            game="uno",
            expected_version=expected_version,
            mutate=lambda _session, state, player: uno.call_uno(state, player["key"]),
        )

    async def catch_uno(self, room_id, user, userid, *, expected_version=None):
        return await self._direct_transition(
            room_id,
            user,
            userid,
            game="uno",
            expected_version=expected_version,
            mutate=lambda _session, state, player: uno.catch_uno(state, player["key"]),
        )

    async def begin_delivery(self, room_id, user, userid, *, expected_version=None):
        key = self._resolve_room(room_id, user, userid)
        async with self._lock(key):
            current = self._require_session(key)
            self._check_version(current, expected_version)
            if current["phase"] != "active":
                raise SessionError("This card game is not ready to deliver a private turn.")
            player = self._participant(current, user, userid)
            current_player = current["state"].get("current_player")
            if current_player is not None and player["key"] != current_player:
                raise SessionError("Only the current player can open private turn delivery.")
            candidate = copy.deepcopy(current)
            candidate.update(
                {
                    "phase": "delivering",
                    "pause_reason": "delivery",
                    "paused_player": player["key"],
                    "turn_deadline": None,
                    "delivery_deadline": current.get("turn_deadline"),
                    "pending_delivery": [player["key"]],
                    "actions": {},
                    "version": candidate["version"] + 1,
                }
            )
            self._save(key, candidate)
            self._sessions[key] = candidate
        self._cancel_task(key)
        return self._transition(candidate, {"kind": "delivery_started"})

    async def finish_delivery(
        self,
        room_id,
        user,
        userid,
        *,
        expected_version=None,
    ):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            self._check_version(current, expected_version)
            if current["phase"] != "delivering":
                raise SessionError("This card game has no private delivery in progress.")
            player = self._participant(current, user, userid)
            if current.get("paused_player") != player["key"]:
                raise SessionError("That private delivery belongs to another player.")
            candidate = copy.deepcopy(current)
            candidate.update(
                {
                    "phase": "active",
                    "pause_reason": None,
                    "paused_player": None,
                    "turn_deadline": (
                        candidate.get("delivery_deadline")
                        or float(self._now()) + TURN_SECONDS
                    ),
                    "delivery_deadline": None,
                    "pending_delivery": [],
                }
            )
            self._save(key, candidate)
            self._sessions[key] = candidate
        return self._transition(candidate, {"kind": "delivery_finished"})

    async def pause_for_delivery(
        self, room_id, user, userid, *, pending_delivery=None
    ):
        key = self._resolve_room(room_id, user, userid)
        async with self._lock(key):
            current = self._require_session(key)
            player = self._participant(current, user, userid)
            if current["phase"] == "finished":
                return self._transition(current, {"kind": "finished"})
            candidate = copy.deepcopy(current)
            pending = (
                list(candidate.get("pending_delivery") or [player["key"]])
                if pending_delivery is None else list(pending_delivery)
            )
            player_keys = self._player_keys(candidate)
            if (
                not pending
                or pending[0] != player["key"]
                or len(pending) != len(set(pending))
                or any(item not in player_keys for item in pending)
            ):
                raise SessionError("Invalid private delivery recovery queue.")
            candidate.update(
                {
                    "phase": "paused",
                    "pause_reason": "delivery",
                    "paused_player": player["key"],
                    "turn_deadline": None,
                    "delivery_deadline": None,
                    "pending_delivery": pending,
                    "actions": {},
                    "version": candidate["version"] + 1,
                }
            )
            self._save(key, candidate)
            self._sessions[key] = candidate
        self._cancel_task(key)
        return self._transition(candidate, {"kind": "paused", "reason": "delivery"})

    async def authorize_resume(
        self, room_id, user, userid, *, expected_version=None
    ):
        key = self._resolve_room(room_id, user, userid)
        async with self._lock(key):
            current = self._require_session(key)
            self._check_version(current, expected_version)
            if current["phase"] != "paused":
                raise SessionError("This card game is not paused.")
            player = self._participant(current, user, userid)
            if current.get("paused_player") != player["key"]:
                raise SessionError("Only the paused player can resume this card game.")
            return {
                "snapshot": copy.deepcopy(current),
                "player": copy.deepcopy(player),
            }

    async def resume(self, room_id, user, userid, *, expected_version=None):
        key = self._resolve_room(room_id, user, userid)
        async with self._lock(key):
            current = self._require_session(key)
            self._check_version(current, expected_version)
            if current["phase"] != "paused":
                raise SessionError("This card game is not paused.")
            player = self._participant(current, user, userid)
            if current.get("paused_player") != player["key"]:
                raise SessionError("Only the paused player can resume this card game.")
            candidate = copy.deepcopy(current)
            event = {"kind": "resume", "player": player["key"]}
            if candidate["game"] == "rang" and candidate["state"].get("phase") == "paused":
                try:
                    event = rang.resume(candidate["state"], player["key"])
                except ValueError as exc:
                    raise SessionError(str(exc)) from exc
            candidate["phase"] = "active"
            candidate["pause_reason"] = None
            candidate["paused_player"] = None
            candidate["pending_delivery"] = []
            candidate["automatic_turns"][player["key"]] = 0
            candidate["turn_deadline"] = float(self._now()) + TURN_SECONDS
            candidate["delivery_deadline"] = None
            candidate["pending_delivery"] = []
            candidate["actions"] = {}
            candidate["version"] += 1
            self._save(key, candidate)
            self._sessions[key] = candidate
        self._cancel_task(key)
        return self._transition(candidate, event)

    async def timeout(self, room_id, *, expected_version):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            self._check_version(current, expected_version)
            if current["phase"] != "active":
                raise StaleAction("The turn is no longer active.")
            candidate = copy.deepcopy(current)
            player_key = candidate["state"].get("current_player")
            if player_key is None:
                raise SessionError("This card game has no current player.")
            try:
                if candidate["game"] == "rang":
                    if candidate["state"].get("phase") == "choosing_trump":
                        suit = self._automatic_trump(candidate["state"], player_key)
                        event = rang.choose_trump(candidate["state"], player_key, suit)
                        event["automatic"] = True
                    else:
                        event = _GAME_ADAPTERS["rang"]["auto"](
                            candidate["state"], player_key
                        )
                else:
                    event = _GAME_ADAPTERS[candidate["game"]]["auto"](
                        candidate["state"], player_key
                    )
            except ValueError as exc:
                raise SessionError(str(exc)) from exc

            candidate["automatic_turns"].setdefault(player_key, 0)
            candidate["automatic_turns"][player_key] += 1
            if (
                candidate["game"] == "uno"
                and candidate["automatic_turns"][player_key] >= 3
                and candidate["state"].get("phase") != "finished"
                and not event.get("removed")
            ):
                players = candidate["state"].get("players", [])
                if len(players) == 2:
                    winner = next(item for item in players if item != player_key)
                    candidate["state"]["phase"] = "finished"
                    candidate["state"]["winner"] = winner
                    candidate["state"]["current_player"] = None
                    event["forfeit"] = True
                else:
                    candidate["phase"] = "paused"
                    candidate["pause_reason"] = "timeout"
                    candidate["paused_player"] = player_key
                    event["paused"] = True
            if (
                candidate["game"] == "rang"
                and candidate["automatic_turns"][player_key] >= 3
                and candidate["state"].get("phase") not in {"finished", "paused"}
            ):
                candidate["state"]["paused_phase"] = candidate["state"]["phase"]
                candidate["state"]["paused_player"] = player_key
                candidate["state"]["phase"] = "paused"
                event["paused"] = True
            if (
                candidate["game"] == "thulla"
                and candidate["automatic_turns"][player_key] >= 3
                and candidate["state"].get("phase") != "finished"
            ):
                active = [
                    item for item in candidate["state"]["players"]
                    if item not in candidate["state"].get("safe_players", [])
                ]
                if len(active) == 2:
                    candidate["state"]["phase"] = "finished"
                    candidate["state"]["loser"] = player_key
                    candidate["state"]["safe_players"] = [
                        item for item in active if item != player_key
                    ]
                    candidate["state"]["current_player"] = None
                    event["forfeit"] = True
                else:
                    candidate["phase"] = "paused"
                    candidate["pause_reason"] = "timeout"
                    candidate["paused_player"] = player_key
                    event["paused"] = True

            candidate["actions"] = {}
            candidate["version"] += 1
            self._sync_phase_and_deadline(candidate)
            self._save(key, candidate)
            self._sessions[key] = candidate
        self._cancel_task(key)
        return self._transition(candidate, event)

    async def end(self, room_id, user, userid, *, is_admin=False):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            player = (self._new_participant(user, userid) if is_admin
                      else self._participant(current, user, userid))
            allowed = (
                player["key"] == current["creator_key"]
                or is_admin
                or player["key"] in self._player_keys(current)
            )
            if not allowed:
                raise SessionError("You are not allowed to end this card game.")
            if not self.store.delete(current["room_id"]):
                raise SessionError("The card game could not be removed from persistent storage.")
            del self._sessions[key]
        self._cancel_task(key)
        self._locks.pop(key, None)
        return {"room_id": current["room_id"], "game": current["game"],
                "event": {"kind": "ended", "player": player["user"]}}

    def public_view(self, room_id):
        session = self._sessions.get(self._room_key(room_id))
        if session is None:
            return None
        return self._public_view_for_session(session)

    def _public_view_for_session(self, session):
        if session["phase"] == "lobby":
            return {
                "game": session["game"],
                "phase": "lobby",
                "players": [player["user"] for player in session["players"]],
                "player_count": len(session["players"]),
                "minimum": _GAME_LIMITS[session["game"]][0],
                "maximum": _GAME_LIMITS[session["game"]][1],
                "deadline": session["lobby_deadline"],
                "version": session["version"],
            }
        view = _GAME_ADAPTERS[session["game"]]["public"](
            copy.deepcopy(session["state"])
        )
        if not isinstance(view, dict):
            raise ValueError("card public projection must be a mapping")
        names = {player["key"]: player["user"] for player in session["players"]}
        view = self._replace_player_keys(view, names)
        view["phase"] = session["phase"]
        view["deadline"] = session["turn_deadline"]
        view["version"] = session["version"]
        if session.get("paused_player"):
            view["paused_player"] = names.get(
                session["paused_player"], session["paused_player"]
            )
        return view

    def result(self, room_id):
        session = self._sessions.get(self._room_key(room_id))
        if not session or not session.get("settlement"):
            return None
        return copy.deepcopy(session["settlement"]["result"]["record"])

    async def pending_claims(self, room_id):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            settlement = current.get("settlement")
            if not settlement:
                return []
            return [
                copy.deepcopy(item)
                for item in (settlement["result"], *settlement["rewards"])
                if not item.get("claimed")
            ]

    async def ack_claim(self, room_id, award_key):
        key = self._room_key(room_id)
        async with self._lock(key):
            current = self._require_session(key)
            settlement = current.get("settlement")
            if not settlement:
                raise SessionError("This card game has no pending settlement.")
            candidate = copy.deepcopy(current)
            items = (
                candidate["settlement"]["result"],
                *candidate["settlement"]["rewards"],
            )
            item = next(
                (entry for entry in items if entry.get("key") == award_key), None
            )
            if item is None:
                raise SessionError("That card settlement item does not exist.")
            if item.get("claimed"):
                return False
            newly_claimed = self.store.claim_reward(award_key)
            item["claimed"] = True
            self._save(key, candidate)
            self._sessions[key] = candidate
            return newly_claimed

    async def restore(self, *, schedule_active=None):
        schedule_active = self._schedule_tasks if schedule_active is None else schedule_active
        restored = []
        expired = []
        rejected = []
        now = float(self._now())
        for stored_key, raw in self.store.load_all().items():
            if str(stored_key).startswith(BINGO_STORE_PREFIX):
                continue
            try:
                session = self._normalize_snapshot(raw)
            except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                session = None
            if session is None:
                rejected.append(self._rejected_snapshot(stored_key, raw))
                continue
            key = self._room_key(session["room_id"])
            if key in self._sessions or any(
                self._room_key(item["room_id"]) == key for item in restored
            ):
                rejected.append(self._rejected_snapshot(stored_key, raw))
                continue
            if session["phase"] == "lobby" and session["lobby_deadline"] <= now:
                if self.store.delete(session["room_id"]):
                    expired.append({"room_id": session["room_id"], "game": session["game"]})
                self._locks.pop(key, None)
                continue
            self._sessions[key] = session
            stable_key = self._room_key(stored_key)
            if stable_key != key or session != raw:
                self._save(key, session)
            restored.append(copy.deepcopy(session))

        for session in restored:
            if session["phase"] == "lobby" and self._schedule_tasks:
                self.arm_lobby_timer(session["room_id"])
            elif session["phase"] == "active" and schedule_active:
                self.arm_turn_timer(session["room_id"])
        for item in expired:
            await self._notify(self.on_lobby_expired, copy.deepcopy(item))
        return {"restored": restored, "expired": expired, "rejected": rejected}

    def arm_lobby_timer(self, room_id):
        key = self._room_key(room_id)
        session = self._sessions.get(key)
        if not session or session["phase"] != "lobby":
            return False
        self._replace_task(
            key,
            self._deadline_task(
                key, session["version"], session["lobby_deadline"], "lobby"
            ),
        )
        return True

    def arm_turn_timer(self, room_id):
        key = self._room_key(room_id)
        session = self._sessions.get(key)
        if not session or session["phase"] != "active" or session["turn_deadline"] is None:
            return False
        self._replace_task(
            key,
            self._deadline_task(
                key, session["version"], session["turn_deadline"], "turn"
            ),
        )
        return True

    async def close(self):
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _direct_transition(
        self,
        room_id,
        user,
        userid,
        *,
        game,
        expected_version,
        mutate,
    ):
        key = self._resolve_room(room_id, user, userid, game=game)
        async with self._lock(key):
            current = self._require_session(key)
            if current["game"] != game:
                raise SessionError(f"This action belongs to {game.title()}.")
            self._check_version(current, expected_version)
            player = self._participant(current, user, userid)
            return self._manual_transition_locked(
                key,
                current,
                player,
                lambda state: mutate(current, state, player),
            )

    def _manual_transition_locked(self, key, current, player, mutate):
        if current["phase"] != "active":
            raise SessionError("This card game is not accepting actions.")
        candidate = copy.deepcopy(current)
        try:
            event = mutate(candidate["state"])
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        candidate["automatic_turns"][player["key"]] = 0
        rule_timeouts = candidate["state"].get("timeout_counts")
        if isinstance(rule_timeouts, dict) and player["key"] in rule_timeouts:
            rule_timeouts[player["key"]] = 0
        candidate["actions"] = {}
        candidate["version"] += 1
        self._sync_phase_and_deadline(candidate)
        self._save(key, candidate)
        self._sessions[key] = candidate
        self._cancel_task(key)
        return self._transition(candidate, event)

    def _sync_phase_and_deadline(self, candidate):
        state_phase = candidate["state"].get("phase")
        if state_phase == "finished":
            candidate["phase"] = "finished"
            candidate["turn_deadline"] = None
            candidate["delivery_deadline"] = None
            candidate["pause_reason"] = None
            candidate["paused_player"] = None
            if not candidate.get("settlement"):
                candidate["settlement"] = self._terminal_settlement(candidate)
                candidate["result"] = copy.deepcopy(
                    candidate["settlement"]["result"]["record"]
                )
            return
        if state_phase == "paused" or candidate.get("phase") == "paused":
            candidate["phase"] = "paused"
            candidate["turn_deadline"] = None
            candidate["delivery_deadline"] = None
            if state_phase == "paused":
                candidate["pause_reason"] = "timeout"
                candidate["paused_player"] = candidate["state"].get("paused_player")
                candidate["pending_delivery"] = []
            return
        candidate["phase"] = "active"
        candidate["pause_reason"] = None
        candidate["paused_player"] = None
        candidate["pending_delivery"] = []
        candidate["turn_deadline"] = float(self._now()) + TURN_SECONDS
        candidate["delivery_deadline"] = None

    async def _deadline_task(self, key, version, deadline, mode):
        try:
            await self._sleep(max(0.0, float(deadline) - float(self._now())))
            if mode == "lobby":
                transition = await self._finish_lobby_deadline(key, version)
                if transition is None:
                    return
                callback = (self.on_lobby_started
                            if transition.get("snapshot") else self.on_lobby_expired)
            else:
                transition = await self.timeout(key, expected_version=version)
                callback = self.on_timeout
            await self._notify(callback, transition)
        except (asyncio.CancelledError, StaleAction, SessionError):
            return
        finally:
            task = self._tasks.get(key)
            if task is asyncio.current_task():
                self._tasks.pop(key, None)

    async def _finish_lobby_deadline(self, key, expected_version):
        session = self._sessions.get(key)
        if session is None:
            return None
        self._check_version(session, expected_version)
        minimum = _GAME_LIMITS[session["game"]][0]
        if len(session["players"]) < minimum:
            async with self._lock(key):
                session = self._require_session(key)
                self._check_version(session, expected_version)
                if not self.store.delete(session["room_id"]):
                    raise SessionError("The expired lobby could not be removed.")
                del self._sessions[key]
            self._locks.pop(key, None)
            return {"room_id": session["room_id"], "game": session["game"],
                    "event": {"kind": "lobby_expired"}}
        creator = next(
            player for player in session["players"]
            if player["key"] == session["creator_key"]
        )
        return await self.start(
            session["room_id"], creator["user"], creator["userid"],
            expected_version=expected_version,
            gate_delivery=True,
        )

    def _normalize_snapshot(self, raw):
        if not isinstance(raw, dict):
            return None
        required = {
            "schema_version", "session_id", "room_id", "game", "phase",
            "creator_key", "players", "created_at", "version", "state",
        }
        if not required <= set(raw) or raw.get("schema_version") != SNAPSHOT_VERSION:
            return None
        if type(raw.get("version")) is not int or raw["version"] < 1:
            return None
        if raw.get("game") not in _GAME_LIMITS or raw.get("phase") not in {
            "lobby", "active", "delivering", "paused", "finished"
        }:
            return None
        if not isinstance(raw.get("session_id"), str) or not raw["session_id"].strip():
            return None
        if raw.get("room_id") is None or not str(raw["room_id"]).strip():
            return None
        if not self._finite_number(raw.get("created_at")):
            return None
        if not isinstance(raw.get("players"), list) or not raw["players"]:
            return None
        minimum, maximum = _GAME_LIMITS[raw["game"]]
        if not 1 <= len(raw["players"]) <= maximum:
            return None

        session = copy.deepcopy(raw)
        normalized_players = []
        for player in session["players"]:
            if not isinstance(player, dict) or not {"key", "user", "userid"} <= set(player):
                return None
            key = str(player["key"]).strip()
            user = str(player["user"]).strip()
            userid = "" if player["userid"] is None else str(player["userid"]).strip()
            if not key or not user or not userid:
                return None
            normalized_players.append({"key": key, "user": user, "userid": userid})
        session["players"] = normalized_players
        player_keys = [player["key"] for player in normalized_players]
        userids = [player["userid"] for player in normalized_players]
        if len(set(player_keys)) != len(player_keys) or len(set(userids)) != len(userids):
            return None
        if session.get("creator_key") not in set(player_keys):
            return None

        session.setdefault("lobby_deadline", None)
        session.setdefault("turn_deadline", None)
        session.setdefault("delivery_deadline", None)
        session.setdefault("actions", {})
        session.setdefault("automatic_turns", {
            player["key"]: 0 for player in session["players"]
        })
        session.setdefault("pause_reason", None)
        session.setdefault("paused_player", None)
        session.setdefault("pending_delivery", (
            [session["paused_player"]]
            if session.get("paused_player") is not None
            and session.get("phase") in {"delivering", "paused"}
            and session.get("pause_reason") == "delivery"
            else []
        ))
        session.setdefault("result", None)
        session.setdefault("settlement", None)

        if not isinstance(session["actions"], dict):
            return None
        room_key = self._room_key(session["room_id"])
        for action_id, action in session["actions"].items():
            if (
                not self.is_action_id(action_id)
                or not isinstance(action, dict)
                or action.get("version") != session["version"]
                or action.get("room") != room_key
                or action.get("player") not in player_keys
                or action.get("kind") != "play"
                or not isinstance(action.get("card_id"), str)
                or not action["card_id"]
            ):
                return None
        if not isinstance(session["automatic_turns"], dict):
            return None
        if set(session["automatic_turns"]) != set(player_keys) or any(
            type(value) is not int or value < 0
            for value in session["automatic_turns"].values()
        ):
            return None
        if (
            not isinstance(session["pending_delivery"], list)
            or len(session["pending_delivery"]) != len(set(session["pending_delivery"]))
            or any(item not in player_keys for item in session["pending_delivery"])
        ):
            return None

        phase = session["phase"]
        if phase == "lobby":
            if (
                len(player_keys) > maximum
                or session["state"] is not None
                or not self._finite_number(session["lobby_deadline"])
                or session["turn_deadline"] is not None
                or session["delivery_deadline"] is not None
                or session["actions"]
                or session["paused_player"] is not None
                or session["pending_delivery"]
                or session["settlement"] is not None
                or session["result"] is not None
            ):
                return None
            self._public_view_for_session(session)
            return session

        if len(player_keys) < minimum or not isinstance(session.get("state"), dict):
            return None
        if not self._validate_rule_state(session):
            return None
        if session.get("lobby_deadline") is not None:
            return None
        if phase == "active":
            if (
                not self._finite_number(session.get("turn_deadline"))
                or session.get("delivery_deadline") is not None
                or session.get("paused_player") is not None
                or session["pending_delivery"]
                or session["state"].get("phase") in {"paused", "finished"}
            ):
                return None
        elif phase == "delivering":
            if (
                session.get("turn_deadline") is not None
                or not self._finite_number(session.get("delivery_deadline"))
                or session.get("paused_player") not in player_keys
                or not session["pending_delivery"]
                or session["state"].get("phase") in {"paused", "finished"}
            ):
                return None
        elif phase == "paused":
            if (
                session.get("turn_deadline") is not None
                or session.get("delivery_deadline") is not None
                or session.get("paused_player") not in player_keys
                or session.get("pause_reason") not in {"delivery", "timeout"}
                or (
                    session.get("pause_reason") == "delivery"
                    and (
                        not session["pending_delivery"]
                        or session["pending_delivery"][0] != session["paused_player"]
                    )
                )
                or (
                    session.get("pause_reason") == "timeout"
                    and session["pending_delivery"]
                )
            ):
                return None
        elif (
            session.get("turn_deadline") is not None
            or session.get("delivery_deadline") is not None
            or session.get("paused_player") is not None
            or session["pending_delivery"]
            or session["state"].get("phase") != "finished"
        ):
            return None

        if phase == "finished":
            expected = self._terminal_settlement(session)
            if session.get("settlement") is None:
                session["settlement"] = expected
            elif not self._valid_settlement(session["settlement"], expected):
                return None
            record = copy.deepcopy(session["settlement"]["result"]["record"])
            if session.get("result") not in (None, record):
                return None
            session["result"] = record
        elif session.get("settlement") is not None or session.get("result") is not None:
            return None

        if session["phase"] == "delivering":
            session["phase"] = "paused"
            session["pause_reason"] = "delivery"
            session["paused_player"] = (
                session.get("paused_player")
                or (session.get("state") or {}).get("current_player")
            )
            if session["paused_player"] in session["pending_delivery"]:
                session["pending_delivery"] = [session["paused_player"]] + [
                    item for item in session["pending_delivery"]
                    if item != session["paused_player"]
                ]
            session["turn_deadline"] = None
            session["delivery_deadline"] = None
            session["actions"] = {}
            session["version"] += 1
        self._public_view_for_session(session)
        return session

    @staticmethod
    def _finite_number(value):
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        )

    @staticmethod
    def _valid_int(value, minimum=0, maximum=None):
        return (
            type(value) is int
            and value >= minimum
            and (maximum is None or value <= maximum)
        )

    @staticmethod
    def _valid_card(card, expected_cards):
        if (
            not isinstance(card, dict)
            or set(card) != {"id", "suit", "rank", "value"}
            or type(card.get("id")) is not str
        ):
            return False
        expected = expected_cards.get(card["id"])
        return expected is not None and all(
            type(card[field]) is type(expected[field])
            and card[field] == expected[field]
            for field in expected
        )

    def _valid_card_subset(self, cards, expected_cards, expected_count):
        if len(cards) != expected_count:
            return False
        card_ids = [
            card.get("id")
            for card in cards
            if isinstance(card, dict) and type(card.get("id")) is str
        ]
        return (
            len(card_ids) == len(cards)
            and len(set(card_ids)) == len(card_ids)
            and set(card_ids) <= set(expected_cards)
            and all(self._valid_card(card, expected_cards) for card in cards)
        )

    def _valid_complete_deck(self, cards, expected_cards):
        if len(cards) != len(expected_cards):
            return False
        card_ids = [card.get("id") for card in cards if isinstance(card, dict)]
        return (
            len(card_ids) == len(cards)
            and len(set(card_ids)) == len(card_ids)
            and set(card_ids) == set(expected_cards)
            and all(self._valid_card(card, expected_cards) for card in cards)
        )

    def _validate_rule_state(self, session):
        state = session["state"]
        game = session["game"]
        expected_fields = {
            "thulla": _THULLA_STATE_FIELDS,
            "rang": _RANG_STATE_FIELDS,
            "uno": _UNO_STATE_FIELDS,
        }[game]
        if set(state) != expected_fields:
            return False
        session_order = [player["key"] for player in session["players"]]
        session_keys = set(session_order)
        state_players = state.get("players")
        if (
            state.get("game") != game
            or not isinstance(state_players, list)
            or not state_players
            or any(not isinstance(player, str) or not player for player in state_players)
            or len(set(state_players)) != len(state_players)
        ):
            return False
        state_keys = set(state_players)
        if game == "uno":
            if (
                len(state_players) < 2
                or not state_keys <= session_keys
                or state_players != [key for key in session_order if key in state_keys]
            ):
                return False
        elif state_players != session_order:
            return False
        hands = state.get("hands")
        if not isinstance(hands, dict) or set(hands) != state_keys:
            return False
        if any(
            not isinstance(hand, list)
            for hand in hands.values()
        ):
            return False
        current = state.get("current_player")
        if current is not None and current not in state_keys:
            return False

        if game == "thulla":
            return self._validate_thulla_state(state, state_keys)
        if game == "rang":
            return self._validate_rang_state(state, state_keys)
        return self._validate_uno_state(state, state_keys, session_keys)

    def _validate_thulla_state(self, state, player_keys):
        if state.get("phase") not in {"playing", "finished"}:
            return False
        safe = state.get("safe_players")
        loser = state.get("loser")
        trick = state.get("trick")
        waste = state.get("waste")
        if (
            not isinstance(safe, list)
            or len(set(safe)) != len(safe)
            or not set(safe) <= player_keys
            or (loser is not None and loser not in player_keys)
            or not isinstance(trick, list)
            or not isinstance(waste, list)
            or not isinstance(state.get("waste_order"), list)
            or type(state.get("first_trick")) is not bool
        ):
            return False
        if (
            len(state["waste_order"]) != len(_STANDARD_CARDS)
            or len(set(state["waste_order"])) != len(state["waste_order"])
            or set(state["waste_order"]) != set(_STANDARD_CARDS)
        ):
            return False
        if any(
            not isinstance(entry, dict) or set(entry) != {"player", "card"}
            or entry.get("player") not in player_keys
            or not self._valid_card(entry.get("card"), _STANDARD_CARDS)
            for entry in trick
        ):
            return False
        cards = [
            card for hand in state["hands"].values() for card in hand
        ] + [entry["card"] for entry in trick] + waste
        if not self._valid_complete_deck(cards, _STANDARD_CARDS):
            return False
        trick_players = [entry["player"] for entry in trick]
        if len(set(trick_players)) != len(trick_players):
            return False
        if state["phase"] == "finished":
            return (
                loser in player_keys
                and loser not in safe
                and set(safe) == player_keys - {loser}
                and state.get("current_player") is None
            )
        active = player_keys - set(safe)
        turn_order_valid = True
        if trick_players:
            active_order = [
                player for player in state["players"] if player in active
            ]
            start = active_order.index(trick_players[0])
            expected_players = [
                active_order[(start + offset) % len(active_order)]
                for offset in range(len(trick_players))
            ]
            expected_current = active_order[
                (start + len(trick_players)) % len(active_order)
            ]
            turn_order_valid = (
                trick_players == expected_players
                and state.get("current_player") == expected_current
            )
        return (
            loser is None
            and len(active) >= 2
            and state.get("current_player") in active
            and all(not state["hands"][player] for player in safe)
            and set(trick_players) <= active
            and state["current_player"] not in trick_players
            and len(trick) < len(active)
            and turn_order_valid
            and (
                not state["first_trick"]
                or (not safe and not waste and (
                    (
                        not trick
                        and any(
                            card["id"] == "c52"
                            for card in state["hands"][state["current_player"]]
                        )
                    )
                    or (trick and trick[0]["card"]["id"] == "c52")
                ))
            )
        )

    def _validate_rang_state(self, state, player_keys):
        if state.get("phase") not in {"choosing_trump", "playing", "paused", "finished"}:
            return False
        players = state["players"]
        teams = state.get("teams")
        if (
            teams != [[players[0], players[2]], [players[1], players[3]]]
            or state.get("dealer") not in player_keys
            or state.get("trump_caller") not in player_keys
        ):
            return False
        for field in ("current_player", "paused_player"):
            if state[field] is not None and state[field] not in player_keys:
                return False
        if state.get("paused_phase") not in {None, "choosing_trump", "playing"}:
            return False
        trick = state.get("trick")
        stock = state.get("stock")
        timeouts = state.get("timeout_counts")
        if (
            not isinstance(trick, list)
            or not isinstance(stock, list)
            or not isinstance(timeouts, dict)
            or set(timeouts) != player_keys
            or any(not self._valid_int(value) for value in timeouts.values())
            or state.get("winner_team") not in {None, 1, 2}
            or state.get("trump") not in {None, *_SUITS}
            or not self._valid_int(state.get("shuffle_seed"), maximum=2**63 - 1)
            or not self._valid_int(state.get("court_target"), minimum=1)
            or not self._valid_int(state.get("deal_number"), minimum=1)
        ):
            return False
        for field, maximum in (("team_tricks", 7), ("deal_streaks", 6)):
            values = state.get(field)
            if (
                not isinstance(values, list) or len(values) != 2
                or any(not self._valid_int(value, maximum=maximum) for value in values)
            ):
                return False
        courts = state.get("courts")
        if (
            not isinstance(courts, list) or len(courts) != 2
            or any(
                not self._valid_int(value, maximum=state["court_target"])
                for value in courts
            )
            or sum(state["team_tricks"]) > 13
        ):
            return False
        if any(
            not isinstance(entry, dict) or set(entry) != {"player", "card"}
            or entry.get("player") not in player_keys
            or not self._valid_card(entry.get("card"), _STANDARD_CARDS)
            for entry in trick
        ):
            return False
        trick_players = [entry["player"] for entry in trick]
        completed_tricks = sum(state["team_tricks"])
        live_cards = (
            [card for hand in state["hands"].values() for card in hand]
            + stock + [entry["card"] for entry in trick]
        )
        if (
            len(trick) > 3
            or len(set(trick_players)) != len(trick_players)
            or not self._valid_card_subset(
                live_cards,
                _STANDARD_CARDS,
                len(_STANDARD_CARDS) - 4 * completed_tricks,
            )
        ):
            return False

        phase = state["phase"]
        effective_phase = state["paused_phase"] if phase == "paused" else phase
        if phase == "paused":
            if state["paused_player"] not in player_keys or effective_phase is None:
                return False
        elif state["paused_player"] is not None or state["paused_phase"] is not None:
            return False
        if phase == "finished":
            winner = state["winner_team"]
            expected_hand_size = 13 - completed_tricks
            return (
                winner in {1, 2}
                and state["current_player"] is None
                and state["trump"] in _SUITS
                and not stock
                and not trick
                and expected_hand_size >= 0
                and all(
                    len(state["hands"][player]) == expected_hand_size
                    for player in players
                )
                and state["team_tricks"][winner - 1] == 7
                and state["team_tricks"][2 - winner] < 7
                and state["courts"][winner - 1] >= state["court_target"]
            )
        if state["winner_team"] is not None or any(
            value >= state["court_target"] for value in courts
        ) or any(value >= 7 for value in state["team_tricks"]):
            return False
        if effective_phase == "choosing_trump":
            return (
                state["current_player"] == state["trump_caller"]
                and state["trump"] is None
                and not trick
                and state["team_tricks"] == [0, 0]
                and len(stock) == 32
                and all(len(hand) == 5 for hand in state["hands"].values())
            )
        expected_hand_size = 13 - completed_tricks
        if expected_hand_size < 0 or any(
            len(state["hands"][player])
            != expected_hand_size - (1 if player in trick_players else 0)
            for player in players
        ):
            return False
        if trick_players:
            leader_index = players.index(trick_players[0])
            expected_players = [
                players[(leader_index + offset) % len(players)]
                for offset in range(len(trick_players))
            ]
            expected_current = players[
                (leader_index + len(trick_players)) % len(players)
            ]
            if (
                trick_players != expected_players
                or state["current_player"] != expected_current
            ):
                return False
        return (
            effective_phase == "playing"
            and state["current_player"] in player_keys
            and state["current_player"] not in trick_players
            and state["trump"] in _SUITS
            and not stock
        )

    def _validate_uno_state(self, state, player_keys, session_keys):
        if state.get("phase") not in {"playing", "choosing_color", "finished"}:
            return False
        removed = state.get("removed_players")
        if (
            not isinstance(removed, list)
            or len(set(removed)) != len(removed)
            or set(removed) | player_keys != session_keys
            or set(removed) & player_keys
        ):
            return False
        for field in (
            "color_chooser", "wild4_offender", "wild4_target", "winner"
        ):
            if state.get(field) is not None and state[field] not in player_keys:
                return False
        for field in ("scores", "timeout_counts"):
            values = state.get(field)
            if not isinstance(values, dict) or set(values) != player_keys:
                return False
            if any(not self._valid_int(value) for value in values.values()):
                return False
        for field in ("draw_pile", "discard_pile"):
            cards = state.get(field)
            if not isinstance(cards, list):
                return False
        if (
            not state["discard_pile"]
            or type(state.get("direction")) is not int
            or state["direction"] not in {-1, 1}
            or state.get("active_color") not in {None, *_COLORS}
            or state.get("pending_draw_type") not in {None, "draw2", "wild4"}
            or not self._valid_int(state.get("pending_draw"))
            or not self._valid_int(state.get("target"), minimum=1)
            or not self._valid_int(state.get("round_number"), minimum=1)
            or not self._valid_int(state.get("shuffle_seed"), maximum=2**63 - 1)
            or not self._valid_int(state.get("shuffle_counter"))
            or state.get("wild4_had_active_color") not in {None, True, False}
        ):
            return False
        candidates = state.get("pending_round_candidates")
        if (
            not isinstance(candidates, list)
            or len(set(candidates)) != len(candidates)
            or not set(candidates) <= player_keys
            or any(state["hands"][player] for player in candidates)
        ):
            return False
        window = state.get("uno_window")
        if window is not None and (
            not isinstance(window, dict)
            or set(window) != {"player"}
            or window.get("player") not in player_keys
            or len(state["hands"][window["player"]]) != 1
        ):
            return False
        if not self._valid_complete_deck(
            [card for hand in state["hands"].values() for card in hand]
            + state["draw_pile"] + state["discard_pile"],
            _UNO_CARDS,
        ):
            return False
        top_card = state["discard_pile"][-1]
        if (
            top_card["suit"] != "wild"
            and state["active_color"] != top_card["suit"]
        ):
            return False
        if len(state["discard_pile"]) == 1 and state["shuffle_counter"] == 0:
            opening_direction = -1 if top_card["rank"] == "reverse" else 1
            if state["direction"] != opening_direction:
                return False

        pending = state["pending_draw"]
        pending_type = state["pending_draw_type"]
        if pending_type is None:
            if pending != 0:
                return False
        elif pending_type == "draw2":
            if pending < 2 or pending % 2 or state["discard_pile"][-1]["rank"] != "draw2":
                return False
        elif (
            pending < 4
            or pending % 4
            or state["discard_pile"][-1]["rank"] != "wild4"
        ):
            return False

        if pending_type == "wild4":
            if (
                state["wild4_offender"] not in player_keys
                or type(state["wild4_had_active_color"]) is not bool
            ):
                return False
        elif any(state[field] is not None for field in (
            "wild4_offender", "wild4_target", "wild4_had_active_color"
        )):
            return False

        drawn_card_id = state["drawn_card_id"]
        current = state["current_player"]
        if drawn_card_id is not None and (
            not isinstance(drawn_card_id, str)
            or current not in player_keys
            or not state["hands"][current]
            or state["hands"][current][-1]["id"] != drawn_card_id
            or pending != 0
            or state["phase"] != "playing"
        ):
            return False

        phase = state["phase"]
        if phase == "finished":
            if (
                (top_card["rank"] == "wild" and state["active_color"] is not None)
                or (
                    top_card["rank"] == "wild4"
                    and state["active_color"] not in _COLORS
                )
            ):
                return False
            return (
                current is None
                and state["winner"] in player_keys
                and state["color_chooser"] is None
                and state["uno_window"] is None
                and drawn_card_id is None
                and pending_type is None
            )
        if state["winner"] is not None or current not in player_keys:
            return False
        if phase == "choosing_color":
            return (
                state["active_color"] is None
                and state["color_chooser"] == current
                and top_card["rank"] in {"wild", "wild4"}
                and (
                    top_card["rank"] != "wild4"
                    or state["wild4_offender"] == current
                )
                and (
                    pending_type != "wild4"
                    or state["wild4_target"] is None
                )
            )
        return (
            state["active_color"] in _COLORS
            and state["color_chooser"] is None
            and (
                pending_type != "wild4"
                or state["wild4_target"] == current
            )
        )

    @staticmethod
    def _valid_settlement(actual, expected):
        if not isinstance(actual, dict) or set(actual) != {"result", "rewards"}:
            return False
        if not isinstance(actual["rewards"], list):
            return False
        actual_items = [actual["result"], *actual["rewards"]]
        expected_items = [expected["result"], *expected["rewards"]]
        if len(actual_items) != len(expected_items):
            return False
        for item, expected_item in zip(actual_items, expected_items):
            if not isinstance(item, dict) or type(item.get("claimed")) is not bool:
                return False
            comparable = copy.deepcopy(item)
            comparable["claimed"] = False
            if comparable != expected_item:
                return False
        return True

    @staticmethod
    def _rejected_snapshot(stored_key, raw):
        raw = raw if isinstance(raw, dict) else {}
        phase = raw.get("phase")
        return {
            "room_id": raw.get("room_id", stored_key),
            "game": raw.get("game"),
            "phase": phase,
            "active": phase in {"active", "delivering", "paused"},
        }

    def _terminal_settlement(self, session):
        game = session["game"]
        state = session["state"]
        players = {player["key"]: player for player in session["players"]}
        winner_keys, result = _GAME_ADAPTERS[game]["settlement"](state, players)

        base = f"card:{game}:{session['session_id']}"
        return {
            "result": {
                "kind": "result",
                "key": f"{base}:result",
                "record": result,
                "claimed": False,
            },
            "rewards": [
                {
                    "kind": "reward",
                    "key": f"{base}:reward:{player_key}",
                    "player": copy.deepcopy(players[player_key]),
                    "claimed": False,
                }
                for player_key in winner_keys
            ],
        }

    def _state_action_buttons(self, session, player_key, prefix):
        state = session["state"]
        version = session["version"]
        buttons = []
        if session["game"] == "rang" and state.get("phase") == "choosing_trump":
            if state.get("trump_caller") == player_key:
                buttons.extend(
                    {"label": suit.title(), "message": f"{prefix}trump {suit} {version}"}
                    for suit in _SUITS
                )
        elif session["game"] == "uno":
            if state.get("phase") == "choosing_color" and state.get("color_chooser") == player_key:
                buttons.extend(
                    {"label": color.title(), "message": f"{prefix}color {color} {version}"}
                    for color in _COLORS
                )
            if state.get("phase") == "playing" and state.get("current_player") == player_key:
                buttons.append({"label": "Draw", "message": f"{prefix}draw {version}"})
            if state.get("wild4_target") == player_key:
                buttons.append({"label": "Challenge", "message": f"{prefix}challenge {version}"})
            window = state.get("uno_window") or {}
            if window.get("player") == player_key:
                buttons.append({"label": "UNO!", "message": f"{prefix}uno {version}"})
            elif window.get("player") is not None and player_key in state.get("players", []):
                buttons.append({"label": "Catch UNO", "message": f"{prefix}catchuno {version}"})
        return buttons

    def _legal_card_ids(self, session, player_key):
        return _GAME_ADAPTERS[session["game"]]["legal"](
            session["state"], player_key
        )

    @staticmethod
    def _rules_play(game, state, player_key, card_id):
        return _GAME_ADAPTERS[game]["play"](state, player_key, card_id)

    @staticmethod
    def _automatic_trump(state, player_key):
        hand = state["hands"][player_key]
        return max(
            _SUITS,
            key=lambda suit: (
                sum(card["suit"] == suit for card in hand),
                sum(card["value"] for card in hand if card["suit"] == suit),
                -_SUITS.index(suit),
            ),
        )

    def _transition(self, session, event):
        return {
            "room_id": session["room_id"],
            "game": session["game"],
            "event": copy.deepcopy(event),
            "snapshot": copy.deepcopy(session),
            "public": self.public_view(session["room_id"]),
            "lobby": self._lobby_counts(session) if session["phase"] == "lobby" else None,
        }

    @staticmethod
    def _lobby_counts(session):
        minimum, maximum = _GAME_LIMITS[session["game"]]
        return {"players": len(session["players"]), "minimum": minimum, "maximum": maximum}

    def _resolve_room(self, room_id, user, userid, *, game=None):
        if room_id is not None:
            return self._room_key(room_id)
        session = self.find_for_player(
            user, userid, game=game, phases={"active", "paused"}
        )
        if session is None:
            raise SessionError("You are not in a matching active card game.")
        return self._room_key(session["room_id"])

    def _room_for_action(self, room_id, action_id):
        if room_id is not None:
            key = self._room_key(room_id)
            session = self._sessions.get(key)
            if session and action_id in session.get("actions", {}):
                return key
            if any(action_id in item.get("actions", {}) for item in self._sessions.values()):
                raise SessionError("That card action belongs to another room.")
            if session is not None:
                self._raise_unknown_action(session, action_id)
            raise SessionError("There is no card game in this room.")
        matches = [key for key, session in self._sessions.items()
                   if action_id in session.get("actions", {})]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            version = self._action_version(action_id)
            if version is not None and any(session["version"] != version
                                           for session in self._sessions.values()):
                raise StaleAction("That card button is stale; refresh your hand.")
            raise SessionError("That card action is invalid.")
        raise SessionError("That card action is ambiguous.")

    @staticmethod
    def _room_key(room_id):
        return str(room_id)

    def _lock(self, key):
        return self._locks.setdefault(key, asyncio.Lock())

    def _require_session(self, key):
        session = self._sessions.get(key)
        if session is None:
            raise SessionError("There is no card game in this room.")
        return session

    @staticmethod
    def _new_participant(user, userid):
        user = str(user).strip()
        if not user:
            raise SessionError("A player needs a username.")
        userid = "" if userid is None else str(userid).strip()
        if not userid:
            raise SessionError("A player needs a verified user ID.")
        key = f"uid:{userid}"
        return {"key": key, "user": user, "userid": userid}

    @staticmethod
    def _player_keys(session):
        return {player["key"] for player in session["players"]}

    @staticmethod
    def _participant(session, user, userid):
        userid = "" if userid is None else str(userid).strip()
        if not userid:
            raise SessionError("A verified user ID is required for private card games.")
        by_id = [player for player in session["players"]
                 if player.get("userid") == userid]
        if len(by_id) == 1:
            return by_id[0]
        raise SessionError("You are not a player in this card game.")

    @staticmethod
    def _check_version(session, expected_version):
        if expected_version is None:
            return
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError) as exc:
            raise StaleAction("That card button has an invalid version.") from exc
        if expected_version != session["version"]:
            raise StaleAction("That card button is stale; refresh your hand.")

    @staticmethod
    def _new_action_id(version):
        return f"card_{version}_{secrets.token_urlsafe(12)}"

    @staticmethod
    def _action_version(action_id):
        if not CardSessionManager.is_action_id(action_id):
            return None
        try:
            return int(action_id.split("_", 2)[1])
        except (IndexError, ValueError):
            return None

    def _raise_unknown_action(self, session, action_id):
        version = self._action_version(action_id)
        if version is not None and version != session["version"]:
            raise StaleAction("That card button is stale; refresh your hand.")
        raise SessionError("That card action is invalid.")

    def _save(self, key, candidate):
        if not self.store.save(candidate["room_id"], copy.deepcopy(candidate)):
            raise SessionError("The card game could not be saved.")

    @staticmethod
    def _card_label(card):
        suit = str(card.get("suit", "")).title()
        rank = str(card.get("rank", "")).upper()
        return f"{rank} {suit}".strip()

    @staticmethod
    def _replace_player_keys(value, names):
        if isinstance(value, dict):
            return {
                names.get(key, key): CardSessionManager._replace_player_keys(item, names)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [CardSessionManager._replace_player_keys(item, names) for item in value]
        if isinstance(value, str):
            return names.get(value, value)
        return value

    @staticmethod
    def _settlement_complete(session):
        settlement = session.get("settlement")
        if not settlement:
            return False
        return all(item.get("claimed") for item in (
            settlement["result"], *settlement["rewards"]
        ))

    def _replace_task(self, key, coroutine):
        self._cancel_task(key)
        self._tasks[key] = asyncio.create_task(coroutine)

    def _cancel_task(self, key):
        task = self._tasks.pop(key, None)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    @staticmethod
    async def _notify(callback, value):
        if callback is None:
            return
        result = callback(value)
        if inspect.isawaitable(result):
            await result
