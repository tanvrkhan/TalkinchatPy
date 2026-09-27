"""Essential lifecycle and help commands."""

import time

from registry import all_specs, command


STARTED_AT = time.monotonic()
HELP_MESSAGE_LIMIT = 900
HELP_PAGE_LINES = 14


@command("ping", help="Check the bot is alive", category="Meta")
async def ping(bot, context):
    await bot.reply(context, "Pong!")


@command("uptime", help="Show bot uptime", category="Meta")
async def uptime(bot, context):
    await bot.reply(context, f"Uptime: {int(time.monotonic() - STARTED_AT)} seconds")


@command("help", aliases=("commands", "cmds"), help="List commands", category="Meta")
async def help_command(bot, context):
    specs = all_specs()
    values = context.args.split()
    if not values:
        categories = sorted({spec.category for spec in specs}, key=str.casefold)
        lines = ["TalkinChat commands (prefix: , or !)", "Choose a category:"]
        lines.extend(f",help {category.casefold()}" for category in categories)
        await bot.reply(context, "\n".join(lines)[:HELP_MESSAGE_LIMIT])
        return

    page = int(values[-1]) if values[-1].isdigit() else 1
    query = " ".join(values[:-1] if values[-1].isdigit() else values).casefold()
    selected = [spec for spec in specs if spec.category.casefold() == query]
    if not selected:
        selected = [spec for spec in specs
                    if spec.name == query or query in spec.aliases]
    if not selected:
        await bot.reply(context, "Unknown help category or command. Use ,help.")
        return
    pages = max(1, (len(selected) + HELP_PAGE_LINES - 1) // HELP_PAGE_LINES)
    page = max(1, min(page, pages))
    start = (page - 1) * HELP_PAGE_LINES
    title = selected[0].category if len(selected) > 1 else selected[0].name
    lines = [f"{title} commands ({page}/{pages}):"]
    lines.extend(f",{spec.name} - {spec.help}"
                 for spec in selected[start:start + HELP_PAGE_LINES])
    if page < pages:
        lines.append(f"Next: ,help {query} {page + 1}")
    await bot.reply(context, "\n".join(lines)[:HELP_MESSAGE_LIMIT])
