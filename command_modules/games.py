"""Text-first TalkinChat game commands."""

import random

from registry import command
from services import games, slap


_sessions = {}


def _key(context):
    return context.room.casefold()


@command("mathquiz", aliases=("mq",), category="Games", needs_room=True,
         help="Start a math question")
async def mathquiz(bot, context):
    question, answer = games.gen_math()
    _sessions[_key(context)] = {"game": "mathquiz", "answer": answer,
                                "version": random.randint(1000, 9999)}
    await bot.reply(context, f"Math: {question}\nReply with ,guess <answer>.")


@command("scramble", aliases=("unscramble",), category="Games", needs_room=True,
         help="Start a word scramble")
async def scramble(bot, context):
    question, answer = games.scramble()
    _sessions[_key(context)] = {"game": "scramble", "answer": answer.casefold(),
                                "version": random.randint(1000, 9999)}
    await bot.reply(context, f"Unscramble: {question}\nUse ,guess <word>.")


@command("guess", category="Games", needs_room=True, help="Answer the current game")
async def guess(bot, context):
    session = _sessions.get(_key(context))
    if not session:
        await bot.reply(context, "No answerable game is running here.")
        return
    if context.args.strip().casefold() != str(session["answer"]).casefold():
        await bot.reply(context, "Not quite.")
        return
    _sessions.pop(_key(context), None)
    slap.add_xp_once(context.user, context.user_key, 500, f"game:{session['version']}:{context.user_key}")
    await bot.reply(context, f"Correct, {context.user}!")


@command("bingo", category="Games", needs_room=True, help="Create a bingo card")
async def bingo(bot, context):
    card = games.make_bingo_card()
    await bot.reply(context, games.render_bingo_card(card, set(), "Bingo Card"))


@command("wyr", aliases=("wouldyourather",), category="Games", needs_room=True,
         help="Would you rather")
async def would_you_rather(bot, context):
    first, second = games.pick_wyr()
    await bot.reply(context, f"Would you rather:\n1. {first}\n2. {second}")


@command("stopgame", aliases=("gameoff", "endgame"), category="Games",
         needs_room=True, help="Stop the current game")
async def stopgame(bot, context):
    existed = _sessions.pop(_key(context), None)
    await bot.reply(context, "Game ended." if existed else "No game is running here.")


@command("end", category="Games", help="End the current game")
async def end(bot, context):
    if context.is_dm:
        await bot.reply(context, "No DM game is running.")
    else:
        await stopgame(bot, context)
