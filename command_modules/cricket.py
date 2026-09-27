"""Cross-room cricket commands with private numbered choices."""

from registry import command
from services.cricket_manager import CricketManagerError


def _player_key(context):
    return f"uid:{context.user_key}"


@command("cricket", aliases=("cric",), category="Games", needs_room=True,
         help="Open or join cross-room cricket")
async def cricket(bot, context):
    values = context.args.split()
    try:
        team_size = int(values[0]) if values else 3
        overs = int(values[1]) if len(values) > 1 else 3
        stake = int(values[2]) if len(values) > 2 else 0
        lobby = await bot.cricket.open_or_join(
            context.room, context.room, context.user, context.user_key,
            team_size, overs, stake)
    except (ValueError, CricketManagerError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(
        context,
        f"Cricket lobby: {len(lobby['players'])}/{lobby['team_size']} players. "
        "Use ,cricketsolo to play the bot now, or ,cricketqueue to face "
        "another room. Use ,cricketai to add an AI teammate.",
    )


@command("cricketsolo", aliases=("cricsolo",), category="Games", needs_room=True,
         help="Start cricket immediately against AI")
async def cricket_solo(bot, context):
    await _start(bot, context, True)


@command("cricketqueue", aliases=("cricqueue",), category="Games", needs_room=True,
         help="Queue cricket against another room")
async def cricket_queue(bot, context):
    await _start(bot, context, False)


@command("bat", aliases=("batting",), category="Games", needs_room=True,
         help="Choose to bat after winning the toss")
async def bat(bot, context):
    await _choose_toss(bot, context, "bat")


@command("bowl", aliases=("bowling",), category="Games", needs_room=True,
         help="Choose to bowl after winning the toss")
async def bowl(bot, context):
    await _choose_toss(bot, context, "bowl")


async def _start(bot, context, solo):
    try:
        result = await bot.cricket.start(context.room, solo=solo)
    except CricketManagerError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(
        context,
        "Team queued." if result["kind"] == "queued"
        else "Match paired. Toss winner: use ,bat or ,bowl.",
    )


@command("cricketai", category="Games", needs_room=True,
         help="Add an AI player to the cricket lobby")
async def add_ai(bot, context):
    try:
        result = await bot.cricket.add_ai(
            context.room, context.user, context.user_key)
    except CricketManagerError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("cricketleave", aliases=("cricleave",), category="Games", needs_room=True,
         help="Leave the cricket lobby")
async def leave(bot, context):
    try:
        result = await bot.cricket.leave(
            context.room, context.user, context.user_key)
    except CricketManagerError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("cricketend", aliases=("cricend",), category="Games", needs_room=True,
         help="End your cricket lobby or match")
async def end(bot, context):
    try:
        result = await bot.cricket.cancel(
            context.room, player_key=_player_key(context),
            is_admin=context.level in {"admin", "creator"} or context.room_authority)
    except CricketManagerError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("cricketscore", aliases=("cs",), category="Games", needs_room=True,
         help="Show cricket score")
async def score(bot, context):
    match = bot.cricket.match_for_room(context.room)
    await bot.reply(context, str(match) if match else "No cricket match is active here.")


@command("crickettoss", aliases=("ctoss",), category="Games",
         help="Choose batting or bowling after winning the toss")
async def toss(bot, context):
    decision = context.args.strip().casefold()
    if decision not in {"bat", "bowl"}:
        await bot.reply(context, "Use ,bat or ,bowl.")
        return
    await _choose_toss(bot, context, decision)


async def _choose_toss(bot, context, decision):
    player_key = _player_key(context)
    match = (bot.cricket.match_for_room(context.room) if context.room
             else bot.cricket.match_for_player(player_key))
    if not match:
        await bot.reply(context, "No cricket toss is waiting here.")
        return
    try:
        result = await bot.cricket.toss_choice(
            match["match_id"], player_key, decision)
    except (KeyError, CricketManagerError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("b", aliases=tuple(f"b{number}" for number in range(1, 7)),
         category="Games", help="Submit a private cricket choice")
async def choice(bot, context):
    player_key = _player_key(context)
    match = (bot.cricket.match_for_room(context.room) if context.room
             else bot.cricket.match_for_player(player_key))
    if not match:
        await bot.reply(context, "No cricket match is active here.")
        return
    raw = context.invoked_name[1:] if context.invoked_name.startswith("b") else ""
    raw = raw or context.args.split()[0] if context.args else raw
    try:
        number = int(raw)
        innings = match["innings"]
        batting = match["teams"][innings["batting"]]["players"]
        bowling = match["teams"][innings["bowling"]]["players"]
        if any(player["key"] == player_key for player in batting):
            side = "bat"
        elif any(player["key"] == player_key for player in bowling):
            side = "bowl"
        else:
            raise CricketManagerError("You are not playing in this match.")
        result = await bot.cricket.delivery_choice(
            match["match_id"], player_key, side, number, match["revision"])
    except (KeyError, TypeError, ValueError, CricketManagerError) as exc:
        await bot.reply(context, str(exc) or "Use ,b1 through ,b6.")
        return
    await bot.reply(context, str(result))


@command("cricketproxy", aliases=("cproxy",), category="Games",
         help="Choose for your team's AI batter or bowler")
async def proxy(bot, context):
    player_key = _player_key(context)
    match = (bot.cricket.match_for_room(context.room) if context.room
             else bot.cricket.match_for_player(player_key))
    values = context.args.split()
    if not match or len(values) != 2 or values[0].casefold() not in {"bat", "bowl"}:
        await bot.reply(context, "Usage: ,cricketproxy <bat|bowl> <1-6>")
        return
    try:
        result = await bot.cricket.proxy_choice(
            match["match_id"], player_key, values[0].casefold(),
            int(values[1]), match["revision"])
    except (KeyError, ValueError, CricketManagerError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("cricketbet", category="Economy", help="Bet on an active cricket match")
async def bet(bot, context):
    match = bot.cricket.match_for_room(context.room)
    values = context.args.split()
    if not match or len(values) != 2:
        await bot.reply(context, "Usage: ,cricketbet <a|b> <amount> in an active match room")
        return
    try:
        result = await bot.cricket.place_bet(
            match["match_id"], context.user, context.user_key,
            values[0].casefold(), int(values[1]))
    except (ValueError, CricketManagerError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))
