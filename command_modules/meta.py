"""Essential lifecycle and help commands."""

import time

from registry import all_specs, command


STARTED_AT = time.monotonic()


@command("ping", help="Check the bot is alive", category="Meta")
async def ping(bot, context):
    await bot.reply(context, "Pong!")


@command("uptime", help="Show bot uptime", category="Meta")
async def uptime(bot, context):
    await bot.reply(context, f"Uptime: {int(time.monotonic() - STARTED_AT)} seconds")


@command("help", aliases=("commands", "cmds"), help="List commands", category="Meta")
async def help_command(bot, context):
    lines = ["TalkinChat commands (prefix: , or !)"]
    lines.extend(f",{spec.name} - {spec.help}" for spec in all_specs())
    await bot.reply(context, "\n".join(lines))
