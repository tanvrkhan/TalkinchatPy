"""Explicit text fallbacks for baseline commands awaiting protocol support."""

import json
from pathlib import Path

from registry import REGISTRY


def _fallback(name):
    async def handler(bot, context):
        await bot.reply(
            context,
            f",{name} is recognized, but its TalkinChat-safe implementation is not enabled in this release.",
        )
    return handler


def register_fallbacks():
    path = Path(__file__).resolve().parents[1] / "parity" / "howdies-f2567a1.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for item in manifest["commands"]:
        if REGISTRY.get(item["name"]) is not None:
            continue
        aliases = tuple(alias for alias in item["aliases"] if REGISTRY.get(alias) is None)
        REGISTRY.register(
            item["name"], aliases=aliases, handler=_fallback(item["name"]),
            level=item["permission"], category=item["category"],
            help="Recognized compatibility command",
        )


register_fallbacks()
