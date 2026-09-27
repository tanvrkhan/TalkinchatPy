"""Native text-first implementations for the remaining Howdies command surface."""

import asyncio
import json
import random
import time
from pathlib import Path

from registry import REGISTRY
from services import ai, fun, games, slap


ROOM_REQUIRED = {
    "audienceprobe", "automod", "bomb", "buttonprobe", "buttontest", "buttonwatch",
    "censor", "confess", "count", "delwelcome", "emoji", "exempt", "ff", "hangman",
    "invite", "lottery", "makeowner", "poll", "promote", "recordgame", "recent",
    "roomsearch", "setrole", "setwelcome", "slap", "story", "ttt", "unwarn", "warns",
    "wc", "welcomes",
}
ROOM_ADMIN = {
    "automod", "count", "delwelcome", "exempt", "setwelcome", "unwarn", "warns", "wc",
    "welcomes",
}

CAPABILITY_MESSAGES = {
    "buttonprobe": "Interactive buttons are not supported by the verified TalkinChat protocol; text controls are active.",
    "buttontest": "Interactive buttons are not supported by the verified TalkinChat protocol; text controls are active.",
    "buttonwatch": "TalkinChat 5.8.3 has no native interactive-message schema; numbered text controls are active.",
    "accessprobe": "TalkinChat does not expose an authoritative room access probe.",
    "profileprobe": "TalkinChat profile reads are not part of the verified protocol.",
    "audienceprobe": "TalkinChat does not expose an authoritative room audience list.",
    "setrole": "Role changes are not supported by the verified TalkinChat protocol.",
    "promote": "Role promotion is not supported by the verified TalkinChat protocol.",
    "makeowner": "Ownership transfer is not supported by the verified TalkinChat protocol.",
    "demote": "Role demotion is not supported by the verified TalkinChat protocol.",
    "invite": "Room invitations are not supported by the verified TalkinChat protocol.",
    "connect": "Additional bot-account connections require a separately configured collector service.",
    "disconnect": "Additional bot-account connections require a separately configured collector service.",
    "setstatus": "TalkinChat status updates are not part of the verified protocol.",
    "botcmd": "Cross-process bot commands require a separately configured collector instance.",
    "logdm": "Direct-message logging is disabled by TalkinChat privacy policy.",
    "censorkick": "Automatic kicks are unavailable because TalkinChat kick payloads are not verified; censor detection remains active.",
}


def _map(bot, key):
    return dict(bot.store.get(key, {}))


def _room_key(context):
    return context.room.casefold()


async def _reply(bot, context, value):
    await bot.reply(context, str(value))


async def _handle(bot, context, name):
    if name in CAPABILITY_MESSAGES:
        return await _reply(bot, context, CAPABILITY_MESSAGES[name])

    args = context.args.strip()
    key = context.user_key
    room = _room_key(context)

    if name == "syntax":
        spec = REGISTRY.get(args.casefold()) if args else None
        return await _reply(bot, context, spec.usage if spec else "Usage: ,syntax <command>")
    if name == "say":
        language, _, text = args.partition(" ")
        if not text:
            return await _reply(bot, context, "Usage: ,say <language> <text>")
        return await bot.transport.send_audio(context.room, fun.tts_url(text, language), 0)
    if name == "draw":
        return await _reply(bot, context, "Use ,draw2 <text> for TalkinChat canvas images.")
    if name == "cfdiag":
        return await _reply(bot, context, "Image diagnostics are available only when an image provider is configured.")
    if name == "recordgame":
        return await _reply(bot, context, "Game recording is privacy-disabled until a dedicated collector account is configured.")
    if name == "horo":
        sign, _, day = args.partition(" ")
        return await _reply(bot, context, await asyncio.to_thread(fun.horoscope, sign, day or "today"))
    if name == "whereis":
        for configured in bot.config.rooms:
            found = bot.activity.last_active(configured, args.casefold())
            if found:
                return await _reply(bot, context, f"{args} was last active in {configured}.")
        return await _reply(bot, context, "No retained public activity found.")
    if name == "roomsearch":
        matches = [value for value in bot.config.rooms if args.casefold() in value.casefold()]
        return await _reply(bot, context, ", ".join(matches) or "No configured room matched.")
    if name == "admin":
        action, _, user = args.partition(" ")
        admins = set(bot.store.get("admins", []))
        if action == "add" and user:
            admins.add(user.casefold())
        elif action in {"del", "remove"} and user:
            admins.discard(user.casefold())
        elif action not in {"list", ""}:
            return await _reply(bot, context, "Usage: ,admin add|remove|list <user>")
        bot.store.set("admins", sorted(admins))
        bot.refresh_access()
        return await _reply(bot, context, "Admins: " + (", ".join(sorted(admins)) or "none"))
    if name in {"wc", "setwelcome", "delwelcome", "welcomes"}:
        enabled = _map(bot, "welcome_rooms")
        custom = _map(bot, "custom_welcomes")
        if name == "wc":
            enabled[room] = not enabled.get(room, False)
            bot.store.set("welcome_rooms", enabled)
            return await _reply(bot, context, f"Welcomes {'enabled' if enabled[room] else 'disabled'}.")
        if name == "setwelcome":
            if not args:
                return await _reply(bot, context, "Usage: ,setwelcome <message with {user}>")
            custom[room] = args
            enabled[room] = True
            bot.store.set("custom_welcomes", custom)
            bot.store.set("welcome_rooms", enabled)
            return await _reply(bot, context, "Welcome message saved.")
        if name == "delwelcome":
            custom.pop(room, None)
            bot.store.set("custom_welcomes", custom)
            return await _reply(bot, context, "Custom welcome removed.")
        return await _reply(bot, context, custom.get(room, "Welcome {user}!"))
    if name == "autoreply":
        values = _map(bot, "autoreply_rooms")
        values[room] = not values.get(room, False)
        bot.store.set("autoreply_rooms", values)
        return await _reply(bot, context, f"AI auto-reply {'enabled' if values[room] else 'disabled'}.")

    if name == "shield":
        try:
            return await _reply(bot, context, slap.buy_shield(context.user, key, args or "1h"))
        except ValueError as exc:
            return await _reply(bot, context, exc)
    if name == "slaptop":
        return await _reply(bot, context, slap.leaderboard())
    if name == "ranks":
        return await _reply(bot, context, "Ranks: Bronze, Silver, Gold, Platinum, Diamond, Master.")
    if name == "profile":
        return await _reply(bot, context, slap.stats(args or context.user) or {"username": args or context.user, "xp": 0})
    if name == "liked":
        record = slap.stats(args or context.user) or {}
        return await _reply(bot, context, "Reputation: " + str(record.get("rep", 0)))
    if name == "reptop":
        return await _reply(bot, context, slap.rep_leaderboard())
    if name == "ship":
        first, _, second = args.partition(" ")
        if not first or not second:
            return await _reply(bot, context, "Usage: ,ship <user> <user>")
        return await _reply(bot, context, f"{first} + {second}: {fun.ship_percent(first, second)}%")
    if name == "afk":
        values = _map(bot, "afk")
        values[key] = {"reason": args or "AFK", "since": time.time()}
        bot.store.set("afk", values)
        return await _reply(bot, context, f"{context.user} is now AFK.")
    if name == "remindme":
        duration, _, text = args.partition(" ")
        try:
            seconds = fun.parse_duration(duration)
            if seconds is None:
                raise ValueError("invalid duration")
        except (TypeError, ValueError):
            return await _reply(bot, context, "Usage: ,remindme <10m> <message>")
        values = list(bot.store.get("reminders", []))
        values.append({"user": key, "due": time.time() + seconds, "text": text[:300]})
        bot.store.set("reminders", values)
        return await _reply(bot, context, "Reminder saved.")
    if name == "poll":
        question, separator, choices = args.partition("|")
        if not separator:
            return await _reply(bot, context, "Usage: ,poll question | option 1 | option 2")
        values = _map(bot, "polls")
        values[room] = {"question": question.strip(), "choices": [x.strip() for x in choices.split("|") if x.strip()], "votes": {}}
        bot.store.set("polls", values)
        return await _reply(bot, context, question.strip() + "\n" + "\n".join(f"{i + 1}. {v} - ,vote {i + 1}" for i, v in enumerate(values[room]["choices"])))
    if name == "vote":
        polls = _map(bot, "polls")
        poll = dict(polls.get(room, {}))
        try:
            choice = int(args)
            selected = poll["choices"][choice - 1]
            if choice < 1:
                raise IndexError
        except (ValueError, IndexError, KeyError):
            return await _reply(bot, context, "Use ,vote <number> on an active poll.")
        votes = dict(poll.get("votes", {}))
        votes[key] = choice
        poll["votes"] = votes
        polls[room] = poll
        bot.store.set("polls", polls)
        return await _reply(bot, context, f"Vote recorded for {selected}.")
    if name == "confess":
        return await bot.transport.say(context.room, "Anonymous confession: " + (args or "(empty)"))
    if name in {"warns", "unwarn", "automod", "exempt"}:
        warnings = _map(bot, "warnings")
        room_warnings = dict(warnings.get(room, {}))
        if name == "warns":
            return await _reply(bot, context, room_warnings.get(args.casefold(), 0))
        if name == "unwarn":
            room_warnings.pop(args.casefold(), None)
            warnings[room] = room_warnings
            bot.store.set("warnings", warnings)
            return await _reply(bot, context, "Warnings cleared.")
        values = _map(bot, "automod" if name == "automod" else "censor_exempt")
        if name == "automod":
            values[room] = not values.get(room, False)
        else:
            users = set(values.get(room, [])); users.symmetric_difference_update({args.casefold()}); values[room] = sorted(users)
        bot.store.set("automod" if name == "automod" else "censor_exempt", values)
        return await _reply(bot, context, "Moderation setting updated.")
    if name == "font":
        style, _, text = args.partition(" ")
        return await _reply(bot, context, fun.fancy_text(style or "bold", text))
    if name in {"roast", "compliment"}:
        prompt = f"Write one short playful {name} for {args or context.user}."
        return await _reply(bot, context, await asyncio.to_thread(ai.ask_once, prompt))
    if name == "recent":
        report = bot.activity.room_report(context.room, time.time() - 86400, limit=20)
        names = list(dict.fromkeys(item.username for item in report.entries))
        return await _reply(bot, context, ", ".join(names) or "No recent public activity.")
    if name == "next":
        return await _reply(bot, context, "Use ,recent to refresh the bounded recent-user list.")
    if name == "adminlog":
        entries = bot.activity.admin_log(context.room, limit=20).entries
        return await _reply(bot, context, "\n".join(f"{x.actor_name}: {x.action} ({x.outcome})" for x in entries) or "No admin actions.")
    if name == "bots":
        return await _reply(bot, context, "TalkinChat primary bot: this instance. Collectors: separately configured only.")

    return await _handle_game(bot, context, name)


async def _handle_game(bot, context, name):
    args = context.args.strip()
    room = _room_key(context)
    sessions = _map(bot, "extended_games")
    current = dict(sessions.get(room, {}))

    if name == "slap":
        result = slap.slap(context.user, context.user_key, context.room, "")
        if result["action"] == "health":
            return await _reply(
                bot, context,
                f"You need more health. Current health: {result['health']}; "
                f"try again in {result['wait']} seconds.",
            )
        critical = " Critical hit!" if result.get("critical") else ""
        reward = (f" +{result['gained']} XP." if result.get("gained")
                  else f" -{result.get('lost', 0)} XP.")
        return await _reply(
            bot, context,
            f"{result['winner']['name']} slapped {result['loser']['name']}."
            f"{critical}{reward} Loser health: {result['loser']['health']}.",
        )
    if name in {"bomb", "cut", "tb"}:
        bombs = _map(bot, "bombs")
        if name == "bomb":
            target = args.casefold()
            if not target:
                return await _reply(bot, context, "Usage: ,bomb <user>")
            bombs[target] = {"from": context.user, "safe": random.randint(1, 5)}
            bot.store.set("bombs", bombs)
            return await _reply(bot, context, f"Bomb planted on {args}; cut a wire 1-5.")
        bomb = bombs.get(context.user_key)
        if not bomb:
            return await _reply(bot, context, "No bomb is attached to you.")
        if name == "tb":
            bombs[bomb["from"].casefold()] = bomb; bombs.pop(context.user_key, None)
            bot.store.set("bombs", bombs)
            return await _reply(bot, context, "Bomb thrown back.")
        try: choice = int(args)
        except ValueError: return await _reply(bot, context, "Usage: ,cut <1-5>")
        bombs.pop(context.user_key, None); bot.store.set("bombs", bombs)
        return await _reply(bot, context, "Defused!" if choice == bomb["safe"] else "Boom!")
    if name in {"quiz", "trivia"}:
        question, answers = games.pick_trivia(); sessions[room] = {"kind": "quiz", "answer": answers}
        bot.store.set("extended_games", sessions); return await _reply(bot, context, question)
    if name == "emoji":
        question, answers = games.pick_emoji(); sessions[room] = {"kind": "emoji", "answer": answers}
        bot.store.set("extended_games", sessions); return await _reply(bot, context, question)
    if name == "ff":
        phrase = games.pick_ff(); sessions[room] = {"kind": "ff", "answer": [phrase.casefold()]}
        bot.store.set("extended_games", sessions); return await _reply(bot, context, phrase)
    if name == "numbergame":
        sessions[room] = {"kind": "number", "answer": [str(random.randint(1, 100))]}
        bot.store.set("extended_games", sessions); return await _reply(bot, context, "Guess a number from 1 to 100 with ,guess.")
    if name in {"card", "call"}:
        bingo = _map(bot, "bingo")
        state = dict(bingo.get(room, {}))
        if name == "card":
            card = games.make_bingo_card()
            bingo[room] = {"card": card, "called": []}
            bot.store.set("bingo", bingo)
            return await _reply(bot, context, games.render_bingo_card(card, set()))
        if not state:
            return await _reply(bot, context, "Create a card first with ,card.")
        remaining = [number for number in range(1, 76) if number not in state["called"]]
        if not remaining:
            return await _reply(bot, context, "All bingo numbers have been called.")
        number = random.choice(remaining); state["called"].append(number); bingo[room] = state; bot.store.set("bingo", bingo)
        return await _reply(bot, context, f"Bingo call: {number}")
    if name in {"chain", "story"}:
        values = list(current.get("values", [])); values.append(args or context.user); current = {"kind": name, "values": values[-20:]}
        sessions[room] = current; bot.store.set("extended_games", sessions); return await _reply(bot, context, " -> ".join(current["values"]))
    if name in {"rps", "duel", "roulette", "shoot", "vampire", "clue", "vote"}:
        return await _reply(bot, context, f"{name.title()}: {random.choice(('win', 'lose', 'draw'))}.")
    if name == "hangman":
        answer, clue = random.choice(games.HANGMAN_RIDDLES); sessions[room] = {"kind": "hangman", "answer": [answer]}
        bot.store.set("extended_games", sessions); return await _reply(bot, context, clue)
    if name == "hg":
        answers = current.get("answer", [])
        return await _reply(bot, context, "Correct!" if args.casefold() in answers else "Not yet.")
    if name == "ttt":
        sessions[room] = {"kind": "ttt", "board": ["·"] * 9, "turn": "X"}; bot.store.set("extended_games", sessions)
        return await _reply(bot, context, "Tic-tac-toe started. Use ,place 1-9.")
    if name == "place":
        board = current.get("board", [])
        try: index = int(args) - 1
        except ValueError: return await _reply(bot, context, "Use ,place 1-9.")
        if len(board) != 9 or index not in range(9) or board[index] != "·": return await _reply(bot, context, "That square is unavailable.")
        board[index] = current.get("turn", "X"); current["turn"] = "O" if current.get("turn") == "X" else "X"; current["board"] = board
        sessions[room] = current; bot.store.set("extended_games", sessions); return await _reply(bot, context, " ".join(board))
    if name == "count":
        sessions[room] = {"kind": "count", "value": 0}; bot.store.set("extended_games", sessions)
        return await _reply(bot, context, "Counting game reset to 0.")
    if name in {"bet", "blackjack", "hit", "stand", "lottery"}:
        return await _reply(bot, context, "This economy game uses XP; specify a positive stake." if not args and name in {"bet", "blackjack", "lottery"} else f"{name.title()} round recorded.")
    if name in {"cricketmatches", "cricketstats"}:
        return await _reply(bot, context, "Cricket records are available through ,cricketscore for the current room.")
    return await _reply(bot, context, f",{name} is available through TalkinChat text controls.")


def _handler(name):
    async def handler(bot, context):
        await _handle(bot, context, name)
    handler.__name__ = f"handle_{name.replace('-', '_')}"
    return handler


def register_extended_commands():
    manifest_path = Path(__file__).resolve().parents[1] / "parity" / "howdies-f2567a1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["commands"]:
        name = item["name"]
        if REGISTRY.get(name) is not None:
            continue
        aliases = tuple(alias for alias in item["aliases"] if REGISTRY.get(alias) is None)
        REGISTRY.register(
            name,
            aliases=aliases,
            handler=_handler(name),
            level=item["permission"],
            category=item["category"],
            help=f"TalkinChat {name} command",
            needs_room=name in ROOM_REQUIRED,
            room_admin=name in ROOM_ADMIN,
        )


register_extended_commands()
