"""Room membership and capability-aware administration commands."""

from registry import command


@command("room", help="Show this room", category="Room", needs_room=True)
async def room(bot, context):
    await bot.reply(context, f"Room: {context.room}")


@command("join", level="admin", help="Join a room", category="Admin")
async def join(bot, context):
    if not context.args:
        await bot.reply(context, "Usage: ,join <room>")
        return
    await bot.transport.join_room(context.args)
    await bot.reply(context, f"Joined {context.args}.")


@command("leave", aliases=("quit",), level="admin", room_admin=True,
         help="Leave this room", category="Admin", needs_room=True)
async def leave(bot, context):
    await bot.transport.leave_room(context.room)


@command("rj", level="admin", room_admin=True, help="Rejoin this room",
         category="Admin", needs_room=True)
async def rejoin(bot, context):
    await bot.transport.rejoin_room(context.room)


@command("kick", aliases=("k",), level="admin", room_admin=True,
         help="Kick a user", category="Moderation", needs_room=True)
async def kick(bot, context):
    result = await bot.transport.kick(context.room, context.args)
    if not result.supported:
        await bot.reply(context, result.message)


@command("who", aliases=("users", "members", "inroom", "u", "l"),
         help="List room members", category="Room", needs_room=True)
async def who(bot, context):
    result = await bot.transport.room_members(context.room)
    await bot.reply(context, result.message)


@command("rooms", level="admin", help="List configured rooms", category="Admin")
async def rooms(bot, context):
    configured = bot.store.get("rooms", [])
    await bot.reply(context, "Configured rooms: " + (", ".join(configured) or "none"))


@command("config", aliases=("settings", "bi"), level="admin",
         help="Show bot settings", category="Config")
async def config(bot, context):
    await bot.reply(context, f"Prefix: ,\nRooms: {len(bot.store.get('rooms', []))}")


@command("enable", level="admin", help="Enable a command", category="Config")
async def enable(bot, context):
    disabled = set(bot.store.get("disabled", []))
    disabled.discard(context.args.casefold())
    bot.store.set("disabled", sorted(disabled))
    await bot.reply(context, f"Enabled {context.args}.")


@command("disable", level="admin", help="Disable a command", category="Config")
async def disable(bot, context):
    disabled = set(bot.store.get("disabled", []))
    disabled.add(context.args.casefold())
    bot.store.set("disabled", sorted(disabled))
    await bot.reply(context, f"Disabled {context.args}.")


@command("prefix", level="creator", help="Show command prefixes", category="Config")
async def prefix(bot, context):
    await bot.reply(context, "TalkinChat accepts , and !. Help displays comma.")
