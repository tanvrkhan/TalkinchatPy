"""Command metadata and duplicate-safe registration."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


Handler = Callable[..., Awaitable[None]]
LEVELS = {"user": 0, "admin": 1, "creator": 2}


class PermissionDenied(ValueError):
    pass


@dataclass
class DispatchContext:
    user: str
    room: str = ""
    level: str = "user"
    disabled: tuple[str, ...] = ()
    args: str = ""

    @property
    def user_key(self):
        return self.user.strip().casefold()

    @property
    def is_dm(self):
        return not bool(self.room)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: tuple[str, ...] = ()
    level: str = "user"
    help: str = ""
    usage: str = ""
    category: str = "General"
    needs_room: bool = False
    room_admin: bool = False
    handler: Optional[Handler] = None


class CommandRegistry:
    def __init__(self):
        self._names = {}
        self._specs = []

    def register(self, name, *, aliases=(), handler=None, **metadata):
        metadata.setdefault("usage", f",{name.casefold()}")
        spec = CommandSpec(
            name=name.casefold(),
            aliases=tuple(alias.casefold() for alias in aliases),
            handler=handler,
            **metadata,
        )
        keys = (spec.name, *spec.aliases)
        duplicates = [key for key in keys if key in self._names]
        if duplicates:
            raise ValueError(f"duplicate command name or alias: {duplicates[0]}")
        self._specs.append(spec)
        self._names.update((key, spec) for key in keys)
        return spec

    def get(self, name):
        return self._names.get(str(name).casefold())

    def all_specs(self):
        return tuple(self._specs)

    def parse(self, text):
        value = str(text or "").strip()
        if not value or value[0] not in {",", "!"}:
            return None
        command_name, _, args = value[1:].partition(" ")
        if not command_name:
            return None
        return command_name.casefold(), args.strip()

    def authorize(self, spec, context):
        if spec is None:
            raise PermissionDenied("Unknown command.")
        if spec.name in {name.casefold() for name in context.disabled}:
            raise PermissionDenied("This command is disabled.")
        if LEVELS.get(context.level, 0) < LEVELS.get(spec.level, 0):
            raise PermissionDenied("You do not have permission to use this command.")
        if spec.needs_room and context.is_dm:
            raise PermissionDenied("This command must be used in a room.")

    async def dispatch(self, bot, context, text):
        parsed = self.parse(text)
        if parsed is None:
            return False
        name, context.args = parsed
        spec = self.get(name)
        if spec is None:
            return False
        self.authorize(spec, context)
        if spec.handler is None:
            return False
        await spec.handler(bot, context)
        return True


REGISTRY = CommandRegistry()


def command(name, aliases=None, **metadata):
    def decorate(handler):
        REGISTRY.register(name, aliases=aliases or (), handler=handler, **metadata)
        return handler
    return decorate


def get(name):
    return REGISTRY.get(name)


def all_specs():
    return REGISTRY.all_specs()
