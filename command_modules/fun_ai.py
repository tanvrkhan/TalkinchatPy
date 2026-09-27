"""AI and protocol-free utility commands."""

import asyncio

from registry import command
from services import ai, fun


async def _run_reply(bot, context, function, *args):
    try:
        result = await asyncio.to_thread(function, *args)
    except Exception as exc:  # service boundaries return an actionable, safe error
        result = f"Unable to complete that request: {type(exc).__name__}."
    await bot.reply(context, str(result))


@command("calc", aliases=("math",), help="Calculator", category="Fun")
async def calc(bot, context):
    await _run_reply(bot, context, fun.calc, context.args)


@command("roll", aliases=("dice",), help="Roll dice", category="Fun")
async def roll(bot, context):
    await _run_reply(bot, context, fun.roll, context.args or "1d6")


@command("flip", aliases=("coin",), help="Flip a coin", category="Fun")
async def flip(bot, context):
    await _run_reply(bot, context, fun.coin_flip)


@command("8ball", help="Ask the magic 8-ball", category="Fun")
async def eight_ball(bot, context):
    await _run_reply(bot, context, fun.eight_ball, context.args)


@command("joke", aliases=("j",), help="Random joke", category="Fun")
async def joke(bot, context):
    await _run_reply(bot, context, fun.joke)


@command("quote", help="Inspirational quote", category="Fun")
async def quote(bot, context):
    await _run_reply(bot, context, fun.quote)


@command("weather", help="Current weather", category="Fun")
async def weather(bot, context):
    await _run_reply(bot, context, fun.weather, context.args)


@command("wiki", aliases=("wp",), help="Wikipedia summary", category="Fun")
async def wiki(bot, context):
    await _run_reply(bot, context, fun.wiki, context.args)


@command("ud", aliases=("urban",), help="Urban Dictionary", category="Fun")
async def urban(bot, context):
    await _run_reply(bot, context, fun.urban_dictionary, context.args)


@command("define", aliases=("dict",), help="Dictionary definition", category="Fun")
async def define(bot, context):
    await _run_reply(bot, context, fun.define, context.args)


@command("askai", aliases=("ai", "ask"), help="Ask local AI", category="Fun")
async def ask_ai(bot, context):
    if not context.args:
        await bot.reply(context, "Usage: ,askai <question>")
        return
    await _run_reply(bot, context, ai.ask, context.user_key, context.args)


@command("translate", help="AI translation", category="Fun")
async def translate(bot, context):
    parts = context.args.split(maxsplit=2)
    if len(parts) != 3:
        await bot.reply(context, "Usage: ,translate <source> <target> <text>")
        return
    await _run_reply(bot, context, ai.translate, *parts)


@command("tr", help="Quick translation", category="Fun")
async def quick_translate(bot, context):
    target, _, text = context.args.partition(" ")
    if not target or not text:
        await bot.reply(context, "Usage: ,tr <language-code> <text>")
        return
    await _run_reply(bot, context, fun.translate, target, text)
