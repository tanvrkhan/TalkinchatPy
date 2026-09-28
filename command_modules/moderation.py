"""Moderation, activity, and privacy-aware reporting commands."""

import os
import time

from registry import command


def _room_map(bot, key, room):
    values = dict(bot.store.get(key, {}))
    return values, list(values.get(room.casefold(), []))


@command("censor", category="Censor", needs_room=True, room_admin=True,
         help="Manage censored words")
async def censor(bot, context):
    action, _, word = context.args.partition(" ")
    values, words = _room_map(bot, "censor_words", context.room)
    if action == "add" and word:
        if word.casefold() not in words:
            words.append(word.casefold())
    elif action in {"del", "remove"} and word:
        words = [item for item in words if item != word.casefold()]
    else:
        await bot.reply(context, "Censored words: " + (", ".join(words) or "none"))
        return
    values[context.room.casefold()] = words
    bot.store.set("censor_words", values)
    await bot.reply(context, "Censor list updated.")


@command("warn", category="Moderation", needs_room=True, room_admin=True,
         help="Warn a user")
async def warn(bot, context):
    target = context.args.casefold()
    values = dict(bot.store.get("warnings", {}))
    room = dict(values.get(context.room.casefold(), {}))
    room[target] = int(room.get(target, 0)) + 1
    values[context.room.casefold()] = room
    bot.store.set("warnings", values)
    await bot.reply(context, f"{context.args}: warning {room[target]}.")


@command("mute", category="Moderation", needs_room=True, room_admin=True,
         help="Mute a user")
async def mute(bot, context):
    await bot.reply(context, "Mute is not supported by the verified TalkinChat protocol.")


@command("unmute", category="Moderation", needs_room=True, room_admin=True,
         help="Unmute a user")
async def unmute(bot, context):
    await bot.reply(context, "Mute is not supported by the verified TalkinChat protocol.")


@command("censorkick", category="Censor", needs_room=True, room_admin=True,
         help="Kick users who post censored words")
async def censorkick(bot, context):
    value = context.args.strip().casefold()
    rooms = dict(bot.store.get("censorkick_rooms", {}))
    room = context.room.casefold()
    if value in {"on", "1"}:
        rooms[room] = True
    elif value in {"off", "0"}:
        rooms[room] = False
    elif value:
        await bot.reply(context, "Usage: ,censorkick <on|off>")
        return
    bot.store.set("censorkick_rooms", rooms)
    await bot.reply(context, f"Censor kick is {'on' if rooms.get(room, False) else 'off'}.")


@command("recordgame", level="creator", category="Config", needs_room=True,
         help="Record public game events for protocol analysis")
async def recordgame(bot, context):
    values = context.args.split()
    action = values[0].casefold() if values else "status"
    try:
        if action == "start" and len(values) >= 3:
            session = bot.game_recorder.start(
                context.room, values[1], " ".join(values[2:]), context.user)
            await bot.reply(context, f"Recording {session['game']} public room events.")
            return
        if action == "stop":
            session = bot.game_recorder.stop(context.room)
            await bot.reply(
                context,
                f"Recording saved: {session['events']} public events in "
                f"{os.path.basename(session['path'])}.")
            return
        if action == "status":
            session = bot.game_recorder.status(context.room)
            await bot.reply(
                context,
                f"Recording {session['game']}: {session['events']} public events."
                if session else "No game recording is active in this room.")
            return
    except ValueError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, "Usage: ,recordgame start <bot> <game> | status | stop")


@command("lastactive", level="admin", room_admin=True, category="Admin", needs_room=True,
         help="Show last public activity")
async def lastactive(bot, context):
    activity = bot.activity.last_active(context.room, context.args.casefold())
    await bot.reply(context, str(activity) if activity else "No retained public activity found.")


@command("roomreport", level="admin", room_admin=True, category="Admin", needs_room=True,
         help="Show room activity report")
async def roomreport(bot, context):
    report = bot.activity.room_report(context.room, since=time.time() - 86400, limit=20)
    await bot.reply(context, f"24h public messages: {report.message_count}; events: {len(report.entries)}")


@command("history", level="creator", category="Config", help="Search retained public history")
async def history(bot, context):
    rows = bot.activity.creator_search(context.args)
    await bot.reply(context, "\n".join(f"{row.username}: {row.text}" for row in rows[:20]) or "No matches.")
