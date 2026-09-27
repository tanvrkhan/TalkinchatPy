"""Economy and social commands backed by the TalkinChat-owned slap ledger."""

import asyncio

from registry import command
from services import slap


async def _call(bot, context, function, *args):
    try:
        result = await asyncio.to_thread(function, *args)
    except (ValueError, KeyError) as exc:
        await bot.reply(context, str(exc))
        return None
    return result


@command("xp", aliases=("score", "myxp", "bal", "xm"), help="Show XP", category="Economy")
async def xp(bot, context):
    await bot.reply(context, f"{context.user}: {slap.get_xp(context.user)} XP")


@command("market", aliases=("store",), help="Browse the market", category="Economy")
async def market(bot, context):
    items = slap.market_items()
    await bot.reply(context, "Market:\n" + "\n".join(
        f"{item['id']}: {item['cost']} XP" for item in items))


@command("buy", help="Buy a market item", category="Economy")
async def buy(bot, context):
    result = await _call(bot, context, slap.buy_item,
                         context.user, context.user_key, context.args.casefold())
    if result is not None:
        message = "Purchase complete." if result.get("ok") else "Purchase failed: " + result.get("error", "unknown")
        await bot.reply(context, message)


@command("daily", help="Claim daily XP", category="Economy")
async def daily(bot, context):
    result = await _call(bot, context, slap.claim_daily, context.user, context.user_key)
    if result is not None:
        await bot.reply(context, str(result))


@command("give", aliases=("pay",), help="Transfer XP", category="Economy")
async def give(bot, context):
    target, _, amount = context.args.partition(" ")
    try:
        value = int(amount)
    except ValueError:
        await bot.reply(context, "Usage: ,give <user> <amount>")
        return
    result = await _call(bot, context, slap.transfer,
                         context.user, context.user_key, target, value)
    if result is not None:
        await bot.reply(context, str(result))


@command("rank", aliases=("level",), help="Show rank", category="Economy")
async def rank(bot, context):
    value = slap.get_xp(context.user)
    await bot.reply(context, str(slap.rank_for(value)))


@command("rep", help="Give reputation", category="Social")
async def rep(bot, context):
    result = await _call(bot, context, slap.add_rep, context.user, context.args)
    if result is not None:
        await bot.reply(context, str(result))


@command("marry", help="Propose to a user", category="Social")
async def marry(bot, context):
    result = await _call(bot, context, slap.marry, context.user, context.args)
    if result is not None:
        await bot.reply(context, str(result))


@command("divorce", help="End a marriage", category="Social")
async def divorce(bot, context):
    result = await _call(bot, context, slap.divorce, context.user)
    if result is not None:
        await bot.reply(context, str(result))


@command("couples", help="List couples", category="Social")
async def couples(bot, context):
    await bot.reply(context, str(slap.couples()))


@command("spin", aliases=("s",), help="Spin for a gift", category="Economy")
async def spin(bot, context):
    result = await _call(bot, context, slap.spin, context.user, context.user_key)
    if result is not None:
        await bot.reply(context, str(result))
