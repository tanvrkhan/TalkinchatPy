"""Text controls for persistent Thulla, Rang, and UNO sessions."""

from registry import command
from services.card_session import SessionError


async def _session(bot, context, game):
    try:
        session = await bot.card_sessions.join_or_create(
            context.room, game, context.user, context.user_key)
    except SessionError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, f"{game.title()} lobby: {len(session['participants'])} player(s). Use ,start.")


@command("thulla", category="Games", needs_room=True, help="Join a Thulla lobby")
async def thulla(bot, context):
    await _session(bot, context, "thulla")


@command("rang", category="Games", needs_room=True, help="Join a Rang lobby")
async def rang(bot, context):
    await _session(bot, context, "rang")


@command("uno", category="Games", needs_room=True, help="Join an UNO lobby")
async def uno(bot, context):
    await _session(bot, context, "uno")


@command("start", category="Games", needs_room=True, help="Start the card lobby")
async def start(bot, context):
    try:
        session = await bot.card_sessions.start(context.room, context.user, context.user_key)
    except SessionError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, f"{session['game'].title()} started. Use ,hand in DM for private cards.")


@command("hand", category="Games", help="Show your private hand")
async def hand(bot, context):
    try:
        value = await bot.card_sessions.private_hand(
            context.room or None, context.user, context.user_key)
    except SessionError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.transport.send_dm(context.user, str(value))


async def _versioned(bot, context, method, value=None):
    parts = context.args.split()
    try:
        version = int(parts[-1]) if parts and parts[-1].isdigit() else None
        if value:
            choice = parts[0] if parts else ""
            result = await method(context.room, context.user, context.user_key,
                                  choice, expected_version=version)
        else:
            result = await method(context.room, context.user, context.user_key,
                                  expected_version=version)
    except (SessionError, ValueError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("trump", category="Games", needs_room=True, help="Choose Rang trump")
async def trump(bot, context):
    await _versioned(bot, context, bot.card_sessions.choose_trump, True)


@command("color", category="Games", needs_room=True, help="Choose UNO color")
async def color(bot, context):
    await _versioned(bot, context, bot.card_sessions.choose_color, True)


@command("challenge", category="Games", needs_room=True, help="Challenge UNO draw four")
async def challenge(bot, context):
    await _versioned(bot, context, bot.card_sessions.challenge)


@command("catchuno", category="Games", needs_room=True, help="Catch missed UNO")
async def catchuno(bot, context):
    await _versioned(bot, context, bot.card_sessions.catch_uno)


@command("resume", category="Games", needs_room=True, help="Resume a paused card game")
async def resume(bot, context):
    await _versioned(bot, context, bot.card_sessions.resume)


@command("playcard", aliases=("pc",), category="Games", needs_room=True,
         help="Play a card using its private action id")
async def play_card(bot, context):
    if not context.args:
        await bot.reply(context, "Usage: ,playcard <action-id>")
        return
    try:
        result = await bot.card_sessions.play(
            context.room, context.user, context.user_key, context.args.split()[0])
    except SessionError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("drawcard", aliases=("dc",), category="Games", needs_room=True,
         help="Draw a card on your turn")
async def draw_card(bot, context):
    try:
        version = int(context.args) if context.args.isdigit() else None
        result = await bot.card_sessions.draw(
            context.room, context.user, context.user_key,
            expected_version=version)
    except (SessionError, ValueError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))
