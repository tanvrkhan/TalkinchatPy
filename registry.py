"""Command metadata and duplicate-safe registration."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


Handler = Callable[..., Awaitable[None]]


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
