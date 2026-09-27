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


def _target(context):
    return context.args.strip().split()[0].lstrip("@") if context.args.strip() else ""


async def _set_role(bot, context, role, target=""):
    if role == "owner" and context.level != "creator":
        await bot.reply(context, "Only a bot creator can transfer room ownership.")
        return
    target = target or _target(context)
    if not target:
        await bot.reply(context, f"Usage: ,{context.invoked_name} <user>")
        return
    result = await bot.transport.set_role(context.room, target, role)
    if result.supported:
        await bot.reply(context, f"Role change requested: {target} -> {role}.")
    else:
        await bot.reply(context, result.message)


@command("kick", aliases=("k",), room_admin=True,
         help="Kick a user", category="Moderation", needs_room=True)
async def kick(bot, context):
    target = _target(context)
    if not target:
        await bot.reply(context, "Usage: ,kick <user>")
        return
    result = await bot.transport.kick(context.room, target)
    await bot.reply(
        context,
        f"Kick requested for {target}." if result.supported else result.message,
    )


@command("admin", category="Moderation", room_admin=True,
         help="Make a user a room admin or manage bot admins")
async def admin(bot, context):
    action, _, value = context.args.strip().partition(" ")
    if action.casefold() in {"add", "remove", "del", "list"}:
        if context.level != "creator":
            await bot.reply(context, "Only a bot creator can manage bot admins.")
            return
        admins = set(bot.store.get("admins", []))
        if action.casefold() == "add" and value:
            admins.add(value.casefold())
        elif action.casefold() in {"remove", "del"} and value:
            admins.discard(value.casefold())
        elif action.casefold() != "list":
            await bot.reply(context, "Usage: ,admin add|remove|list <user>")
            return
        bot.store.set("admins", sorted(admins))
        bot.refresh_access()
        await bot.reply(context, "Bot admins: " + (", ".join(sorted(admins)) or "none"))
        return
    if not context.room:
        await bot.reply(context, "Use ,admin <user> in a room, or ,admin add|remove|list.")
        return
    await _set_role(bot, context, "admin", action.lstrip("@"))


@command("promote", aliases=("a",), category="Moderation", needs_room=True,
         room_admin=True, help="Make a user a room admin")
async def promote(bot, context):
    await _set_role(bot, context, "admin")


@command("owner", aliases=("makeowner", "o"), category="Moderation", needs_room=True,
         room_admin=True, help="Make a user a room owner")
async def owner(bot, context):
    await _set_role(bot, context, "owner")


@command("member", aliases=("demote", "m", "d"), category="Moderation", needs_room=True,
         room_admin=True, help="Set a user's room role to member")
async def member(bot, context):
    await _set_role(bot, context, "member")


@command("setrole", aliases=("role",), category="Moderation", needs_room=True,
         room_admin=True, help="Set a user's room role")
async def set_role(bot, context):
    values = context.args.split()
    if len(values) != 2 or values[1].casefold() not in {"owner", "admin", "member", "none"}:
        await bot.reply(context, "Usage: ,setrole <user> <owner|admin|member|none>")
        return
    await _set_role(bot, context, values[1].casefold(), values[0].lstrip("@"))


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
