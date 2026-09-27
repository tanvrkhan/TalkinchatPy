"""Cross-room cricket commands with private numbered choices."""

from registry import command
from services.cricket_manager import CricketManagerError


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
    await bot.reply(context, f"Cricket lobby: {len(lobby['players'])}/{lobby['team_size']} players. Use ,bat to queue or ,bowl solo.")


@command("bat", aliases=("batting",), category="Games", needs_room=True,
         help="Queue the cricket team")
async def bat(bot, context):
    await _start(bot, context, False)


@command("bowl", aliases=("bowling",), category="Games", needs_room=True,
         help="Start cricket against AI")
async def bowl(bot, context):
    await _start(bot, context, True)


async def _start(bot, context, solo):
    try:
        result = await bot.cricket.start(context.room, solo=solo)
    except CricketManagerError as exc:
        await bot.reply(context, str(exc))
        return
    await bot.reply(context, "Team queued." if result["kind"] == "queued" else "Match paired. Captains will receive toss choices privately.")


@command("cricketscore", aliases=("cs",), category="Games", needs_room=True,
         help="Show cricket score")
async def score(bot, context):
    match = bot.cricket.match_for_room(context.room)
    await bot.reply(context, str(match) if match else "No cricket match is active here.")


@command("b", aliases=tuple(f"b{number}" for number in range(1, 7)),
         category="Games", help="Submit a private cricket choice")
async def choice(bot, context):
    await bot.reply(context, "Use the numbered choice and revision sent to you by DM; stale choices are rejected.")


@command("cricketbet", category="Economy", help="Bet on an active cricket match")
async def bet(bot, context):
    await bot.reply(context, "Usage: ,cricketbet <match> <team> <amount>")
