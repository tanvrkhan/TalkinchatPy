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
        page = int(context.args) if context.args.isdigit() else 1
        value = await bot.card_sessions.private_hand(
            context.room or None, context.user, context.user_key, page=page)
    except SessionError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.transport.send_dm(context.user, _format_hand(value))


def _format_hand(value):
    lines = [f"{value['game'].title()} hand ({value['page']}/{value['pages']}):"]
    play_number = 0
    for button in value.get("buttons", []):
        message = str(button.get("message", ""))
        if message.startswith(",playcard card_"):
            play_number += 1
            selection = (str(play_number) if value["page"] == 1
                         else f"{value['page']}.{play_number}")
            message = f",playcard {selection}"
        lines.append(f"{button.get('label', 'Action')}: {message}")
    if len(lines) == 1:
        lines.append("No action is currently available.")
    return "\n".join(lines)


async def _versioned(bot, context, method, value=None):
    parts = context.args.split()
    try:
        version = int(parts[-1]) if parts and parts[-1].isdigit() else None
        if value:
            choice = parts[0] if parts else ""
            result = await method(context.room or None, context.user, context.user_key,
                                  choice, expected_version=version)
        else:
            result = await method(context.room or None, context.user, context.user_key,
                                  expected_version=version)
    except (SessionError, ValueError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("trump", category="Games", help="Choose Rang trump")
async def trump(bot, context):
    await _versioned(bot, context, bot.card_sessions.choose_trump, True)


@command("color", category="Games", help="Choose UNO color")
async def color(bot, context):
    await _versioned(bot, context, bot.card_sessions.choose_color, True)


@command("challenge", category="Games", help="Challenge UNO draw four")
async def challenge(bot, context):
    await _versioned(bot, context, bot.card_sessions.challenge)


@command("calluno", category="Games", help="Call UNO")
async def calluno(bot, context):
    await _versioned(bot, context, bot.card_sessions.call_uno)


@command("catchuno", category="Games", help="Catch missed UNO")
async def catchuno(bot, context):
    await _versioned(bot, context, bot.card_sessions.catch_uno)


@command("resume", category="Games", help="Resume a paused card game")
async def resume(bot, context):
    await _versioned(bot, context, bot.card_sessions.resume)


@command("playcard", aliases=("pc",), category="Games",
         help="Play a card using its private action id")
async def play_card(bot, context):
    if not context.args:
        await bot.reply(context, "Usage: ,playcard <action-id>")
        return
    try:
        action = context.args.split()[0]
        selection = action.split(".", 1)
        if all(part.isdigit() for part in selection):
            page = int(selection[0]) if len(selection) == 2 else 1
            choice = int(selection[-1])
            hand_value = await bot.card_sessions.private_hand(
                context.room or None, context.user, context.user_key, page=page)
            actions = [button["message"].split(" ", 1)[1]
                       for button in hand_value.get("buttons", [])
                       if button.get("message", "").startswith(",playcard card_")]
            index = choice - 1
            if index < 0 or index >= len(actions):
                raise SessionError("Choose a listed card number from ,hand.")
            action = actions[index]
        result = await bot.card_sessions.play(
            context.room or None, context.user, context.user_key, action)
    except SessionError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))


@command("drawcard", aliases=("dc",), category="Games",
         help="Draw a card on your turn")
async def draw_card(bot, context):
    try:
        version = int(context.args) if context.args.isdigit() else None
        result = await bot.card_sessions.draw(
            context.room or None, context.user, context.user_key,
            expected_version=version)
    except (SessionError, ValueError) as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, str(result))
