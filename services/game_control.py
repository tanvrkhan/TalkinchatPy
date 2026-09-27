"""Shared discovery, authorization, and shutdown for persistent games."""

import asyncio
from dataclasses import dataclass

import config_store as store
from services.card_session import SessionError


END_ALIASES = frozenset({"end", "stop", "off"})
ROOM_ADMIN_ROLES = frozenset({
    "admin", "owner", "moderator", "mod", "superadmin", "creator",
})

_ALIASES = {
    "bj": "blackjack",
    "raffle": "lottery",
    "tictactoe": "ttt",
    "ng": "number",
    "guessnum": "number",
    "numbergame": "number",
    "wordchain": "chain",
    "mathquiz": "math",
    "mq": "math",
    "emojiguess": "emoji",
    "unscramble": "scramble",
}

_LABELS = {
    "bingo": "Bingo",
    "ttt": "Tic-Tac-Toe",
    "hangman": "Hangman",
    "blackjack": "Blackjack",
    "lottery": "Lottery",
    "roulette": "Roulette",
    "duel": "Duel",
    "vampire": "Vampire",
    "story": "Story",
    "quiz": "Quiz",
    "trivia": "Trivia",
    "scramble": "Scramble",
    "math": "Math Quiz",
    "emoji": "Emoji Quiz",
    "number": "Number Game",
    "chain": "Word Chain",
    "thulla": "Thulla",
    "rang": "Rang",
    "uno": "UNO",
}


def _key(value):
    return str(value or "").strip().casefold()


def _normal_name(value):
    name = _key(value)
    return _ALIASES.get(name, name)


def _names(values):
    result = set()
    for value in values or ():
        if isinstance(value, dict):
            value = value.get("user")
        name = _key(value)
        if name:
            result.add(name)
    return frozenset(result)


@dataclass(frozen=True)
class ActiveGame:
    name: str
    label: str
    kind: str
    state: object
    room_ids: tuple
    participants: frozenset
    starter: str = ""
    owner_only: bool = False


def _game(name, kind, state, rooms=(), participants=(), starter="", owner_only=False):
    return ActiveGame(
        name=name,
        label=_LABELS[name],
        kind=kind,
        state=state,
        room_ids=tuple(room for room in rooms if room is not None),
        participants=_names(participants),
        starter=_key(starter),
        owner_only=owner_only,
    )


def _room_games(bot, ctx):
    room_id = getattr(ctx, "roomid", None)
    if room_id is None:
        hand = getattr(bot, "_bj", {}).get(_key(ctx.user))
        if hand and hand.get("is_dm") and str(hand.get("userid")) == str(ctx.userid):
            yield _game(
                "blackjack", "blackjack", hand,
                participants=(ctx.user,), starter=ctx.user, owner_only=True,
            )
        return

    bingo = getattr(bot, "_bingo", {}).get(room_id)
    if bingo is not None:
        yield _game(
            "bingo", "bingo", bingo, (room_id,),
            bingo.get("players", {}).values(), bingo.get("starter", ""),
        )

    ttt = getattr(bot, "_ttt", {}).get(room_id)
    if ttt is not None:
        players = ttt.get("players", ())
        yield _game("ttt", "ttt", ttt, (room_id,), players,
                    players[0] if players else "")

    hangman = getattr(bot, "_hangman", {}).get(room_id)
    if hangman is not None:
        participants = set(hangman.get("participants", ()))
        participants.add(hangman.get("starter", ""))
        yield _game(
            "hangman", "hangman", hangman, (room_id,), participants,
            hangman.get("starter", ""),
        )

    lottery = getattr(bot, "lottery", {}).get(room_id)
    if lottery is not None:
        yield _game(
            "lottery", "lottery", lottery, (room_id,),
            lottery.get("entrants", ()), lottery.get("starter", ""),
        )

    room_game = getattr(bot, "_room_games", {}).get(room_id)
    if room_game is not None:
        name = _normal_name(room_game.get("type"))
        if name in {"quiz", "trivia", "scramble", "math", "emoji"}:
            participants = set(room_game.get("participants", ()))
            participants.add(room_game.get("starter", ""))
            yield _game(
                name, "room_quiz", room_game, (room_id,), participants,
                room_game.get("starter", ""),
            )

    session = getattr(bot, "_card_sessions", None)
    session = session.get(room_id) if session is not None else None
    if session is not None:
        creator = next((
            player.get("user", "") for player in session.get("players", ())
            if player.get("key") == session.get("creator_key")
        ), "")
        players = session.get("players", ())
        yield _game(
            session["game"], "card", session, (room_id,), players, creator,
        )

    room_hands = [
        (owner, hand) for owner, hand in getattr(bot, "_bj", {}).items()
        if hand.get("roomid") == room_id and not hand.get("is_dm")
    ]
    if room_hands:
        owners = [owner for owner, _hand in room_hands]
        yield _game(
            "blackjack", "blackjack", room_hands, (room_id,), owners, owners[0],
        )


def _global_games(bot, ctx):
    room_id = getattr(ctx, "roomid", None)
    user = _key(getattr(ctx, "user", ""))
    bot_admin = store.has_level(getattr(ctx, "user", ""), "admin")

    roulette = getattr(bot, "roulette", None)
    if roulette is not None:
        players = roulette.get("players", roulette.get("order", ()))
        rooms = roulette.get("rooms") or {
            player.get("room") for player in players if player.get("room") is not None
        }
        if bot_admin or room_id in rooms or user in _names(players):
            yield _game(
                "roulette", "roulette", roulette, rooms, players,
                players[0].get("user", "") if players else "",
            )

    duel = getattr(bot, "duel_pending", None)
    if duel is not None and (
        bot_admin or room_id == duel.get("room") or user == _key(duel.get("user"))
    ):
        yield _game(
            "duel", "duel", duel, (duel.get("room"),), (duel,), duel.get("user", ""),
        )

    vampire = getattr(bot, "vampire_game", None)
    if vampire is not None:
        players = vampire.get("players", ())
        if bot_admin or room_id == vampire.get("room") or user in _names(players):
            yield _game(
                "vampire", "vampire", vampire, (vampire.get("room"),), players,
                players[0].get("user", "") if players else "",
            )

    if getattr(bot, "story_active", False):
        rooms = getattr(bot, "joined_rooms", ())
        participants = set(getattr(bot, "story_participants", ()))
        participants.add(getattr(bot, "story_starter", ""))
        yield _game(
            "story", "story", getattr(bot, "story_lines", ()), rooms,
            participants, getattr(bot, "story_starter", ""),
        )

    active = getattr(bot, "active_game", None)
    if active is not None and active.get("type") in {"number", "chain"}:
        name = active["type"]
        participants = set(active.get("participants", ()))
        participants.add(active.get("starter", ""))
        rooms = getattr(bot, "joined_rooms", ())
        yield _game(
            name, "active", active, rooms, participants, active.get("starter", ""),
        )


def _find_game(bot, ctx, requested_name=None):
    wanted = _normal_name(requested_name) if requested_name else None
    for game in (*tuple(_room_games(bot, ctx)), *tuple(_global_games(bot, ctx))):
        if wanted is None or game.name == wanted:
            return game
    return None


def active_game(bot, ctx):
    """Return the persistent game visible from this message context, if any."""
    return _find_game(bot, ctx)


def _is_admin(ctx):
    if getattr(ctx, "is_dm", False):
        return store.has_level(ctx.user, "admin")
    role = _key(getattr(ctx, "room_role", "none"))
    return role in ROOM_ADMIN_ROLES or store.has_level(ctx.user, "admin")


def can_end(bot, ctx, game):
    """Apply the universal end authorization contract to a discovered game."""
    user = _key(getattr(ctx, "user", ""))
    if game.owner_only:
        return user in game.participants
    return _is_admin(ctx) or user == game.starter or user in game.participants


def _cancel(task):
    if task is not None and task is not asyncio.current_task():
        task.cancel()


async def _remove_game(bot, ctx, game):
    room_id = getattr(ctx, "roomid", None)
    if game.kind == "card":
        try:
            await bot._card_sessions.end(
                room_id, ctx.user, ctx.userid, is_admin=_is_admin(ctx)
            )
        except SessionError as exc:
            await bot.reply(ctx, str(exc))
            return False
        return True

    if game.kind == "bingo":
        if getattr(bot, "_bingo", {}).get(room_id) is not game.state:
            return False
        close = getattr(bot, "_close_bingo", None)
        if close is not None:
            return bool(close(room_id, game.state))
        bot._bingo.pop(room_id, None)
        _cancel(game.state.get("task"))
    elif game.kind == "ttt":
        if getattr(bot, "_ttt", {}).get(room_id) is not game.state:
            return False
        bot._ttt.pop(room_id, None)
    elif game.kind == "hangman":
        if getattr(bot, "_hangman", {}).get(room_id) is not game.state:
            return False
        bot._hangman.pop(room_id, None)
    elif game.kind == "lottery":
        if getattr(bot, "lottery", {}).get(room_id) is not game.state:
            return False
        bot.lottery.pop(room_id, None)
        _cancel(game.state.get("task"))
    elif game.kind == "room_quiz":
        if getattr(bot, "_room_games", {}).get(room_id) is not game.state:
            return False
        bot._room_games.pop(room_id, None)
        _cancel(game.state.get("task"))
    elif game.kind == "blackjack":
        if game.owner_only:
            bot._bj.pop(_key(ctx.user), None)
        elif _is_admin(ctx):
            for owner, _hand in game.state:
                bot._bj.pop(owner, None)
        else:
            bot._bj.pop(_key(ctx.user), None)
    elif game.kind == "roulette":
        if getattr(bot, "roulette", None) is not game.state:
            return False
        bot.roulette = None
        _cancel(game.state.get("task"))
    elif game.kind == "duel":
        if getattr(bot, "duel_pending", None) is not game.state:
            return False
        bot.duel_pending = None
    elif game.kind == "vampire":
        if getattr(bot, "vampire_game", None) is not game.state:
            return False
        bot.vampire_game = None
        _cancel(game.state.get("task"))
        for event_name in ("guess_event", "kill_event"):
            event = game.state.get(event_name)
            if event is not None:
                event.set()
    elif game.kind == "story":
        if not getattr(bot, "story_active", False):
            return False
        bot.story_active = False
        bot.story_lines = []
        bot.story_starter = None
        bot.story_participants = set()
    elif game.kind == "active":
        if getattr(bot, "active_game", None) is not game.state:
            return False
        bot.active_game = None
        _cancel(getattr(bot, "_game_task", None))
        bot._game_task = None
    else:
        return False
    return True


async def _announce(bot, ctx, game):
    action = "cancelled" if game.name == "bingo" else "ended"
    message = (
        f"🛑 {game.label} {action} by {ctx.user}. "
        "No result or reward was awarded."
    )
    if getattr(ctx, "is_dm", False):
        await bot.reply(ctx, message)
        return
    rooms = game.room_ids or (getattr(ctx, "roomid", None),)
    sent = set()
    for room_id in rooms:
        if room_id is not None and room_id not in sent:
            sent.add(room_id)
            await bot.say(room_id, message)


async def end_game(bot, ctx, requested_name=None):
    """End one matching persistent game without applying any game reward."""
    game = _find_game(bot, ctx, requested_name)
    if game is None:
        if requested_name:
            name = _normal_name(requested_name)
            label = _LABELS.get(name, str(requested_name).title())
            await bot.reply(ctx, f"No {label} game is running here.")
        else:
            await bot.reply(ctx, "Nothing persistent is running here to end.")
        return False
    if not can_end(bot, ctx, game):
        await bot.reply(
            ctx,
            "You are not allowed to end this game. Ask a participant or room admin.",
        )
        return False
    removed = await _remove_game(bot, ctx, game)
    if not removed:
        return False
    await _announce(bot, ctx, game)
    return True
