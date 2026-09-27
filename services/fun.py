#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Text-based fun & utility features (mostly new on top of the old bot).

All use free, key-less public APIs or the standard library so the bot works
out of the box.
"""

import ast
import json
import operator
import random
import urllib.parse
import urllib.request

import requests
from bs4 import BeautifulSoup

import config

_TIMEOUT = 12


def _get_json(url, headers=None):
    headers = headers or {"User-Agent": config.DEFAULT_UA}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


# ------------------------------------------------------------------ urban ---
def urban_dictionary(term):
    quoted = urllib.parse.quote(term)
    data = _get_json(f"https://api.urbandictionary.com/v0/define?term={quoted}")
    items = data.get("list", [])
    if not items:
        return f"No result found for {term}"
    definition = items[0]["definition"].replace("[", "").replace("]", "")
    return f"Word: {term}\nDefinition: {definition[:900]}"


# ---------------------------------------------------------------- horoscope -
def horoscope(sign, day="today"):
    """Daily horoscope scraped from horoscope.com (day: today/tomorrow/yesterday)."""
    signs = ["aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
             "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"]
    sign = sign.lower()
    if sign not in signs:
        return "Unknown zodiac sign. Try: " + ", ".join(signs)
    num = signs.index(sign) + 1
    day = day.lower()
    suffix = {"today": "", "tomorrow": "-tomorrow", "yesterday": "-yesterday"}.get(day, "")
    url = ("https://www.horoscope.com/us/horoscopes/general/"
           f"horoscope-general-daily{suffix}.aspx?sign={num}")
    soup = BeautifulSoup(requests.get(url, timeout=_TIMEOUT).content, "html.parser")
    node = soup.find("div", class_="main-horoscope")
    if not node or not node.p:
        return "Could not fetch horoscope right now."
    return f"{sign.capitalize()} ({day}): {node.p.text.strip()}"


# --------------------------------------------------------------------- joke -
def joke():
    try:
        d = _get_json("https://official-joke-api.appspot.com/random_joke")
        return f"{d['setup']}\n{d['punchline']}"
    except Exception:
        return "Couldn't fetch a joke right now."


# -------------------------------------------------------------------- quote -
def quote():
    try:
        d = _get_json("https://zenquotes.io/api/random")
        return f"\"{d[0]['q']}\" — {d[0]['a']}"
    except Exception:
        return "Couldn't fetch a quote right now."


# ------------------------------------------------------------------ weather -
def weather(city):
    try:
        q = urllib.parse.quote(city)
        # wttr.in: free, no key. format=3 -> one-liner.
        with urllib.request.urlopen(f"https://wttr.in/{q}?format=3", timeout=_TIMEOUT) as r:
            return r.read().decode("utf-8", errors="ignore").strip()
    except Exception:
        return f"Couldn't fetch weather for {city}."


# --------------------------------------------------------------------- wiki -
def wiki(query):
    try:
        q = urllib.parse.quote(query.replace(" ", "_"))
        d = _get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}")
        extract = d.get("extract")
        return extract[:900] if extract else f"No wikipedia article for {query}."
    except Exception:
        return f"No wikipedia article for {query}."


# ---------------------------------------------------------------- translate -
def translate(target_lang, text):
    """Free Google translate endpoint (no key)."""
    try:
        params = urllib.parse.urlencode({
            "client": "gtx", "sl": "auto", "tl": target_lang,
            "dt": "t", "q": text,
        })
        d = _get_json(f"https://translate.googleapis.com/translate_a/single?{params}")
        return "".join(seg[0] for seg in d[0])
    except Exception:
        return "Translation failed."


def tts_url(text, lang="en"):
    """Google Translate TTS URL (returns an audio URL to send as a voice note)."""
    return "https://translate.google.com/translate_tts?" + urllib.parse.urlencode({
        "ie": "UTF-8", "q": text, "tl": lang, "ttsspeed": "1",
        "total": "1", "idx": "0", "client": "tw-ob", "textlen": str(len(text)),
    })


# --------------------------------------------------------- dice / 8ball etc -
_EIGHTBALL = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "You may rely on it.",
    "Most likely.", "Outlook good.", "Signs point to yes.", "Reply hazy, try again.",
    "Ask again later.", "Cannot predict now.", "Don't count on it.", "My reply is no.",
    "Very doubtful.", "Outlook not so good.",
]


def eight_ball(_question=""):
    return random.choice(_EIGHTBALL)


def roll(spec="1d6"):
    """Roll dice, e.g. '2d20'. Returns a text result."""
    try:
        n, sides = spec.lower().split("d")
        n = int(n or 1)
        sides = int(sides)
        if not (1 <= n <= 50 and 2 <= sides <= 1000):
            return "Try something like !roll 2d6 (up to 50 dice, 1000 sides)."
        rolls = [random.randint(1, sides) for _ in range(n)]
        total = sum(rolls)
        return f"🎲 {rolls} = {total}" if n > 1 else f"🎲 {total}"
    except Exception:
        return "Usage: !roll 2d6"


def coin_flip():
    return "🪙 " + random.choice(["Heads", "Tails"])


_CUTE_NAMES = [
    "Sunshine", "Cupcake", "Butterfly", "Marshmallow", "Sweet Pea", "Honeybee",
    "Little Star", "Angel", "Peach", "Bubbles", "Muffin", "Sunflower", "Teddy",
    "Dolphin", "Panda", "Koala", "Cookie", "Sparkle", "Rainbow", "Blossom",
    "Snowflake", "Kitten", "Bunny", "Duckling", "Pumpkin", "Cherry", "Waffle",
    "Jellybean", "Buttercup", "Moonbeam", "Sugarplum", "Twinkle", "Cinnamon",
    "Hazelnut", "Maple", "Pebble", "Poppy", "Clover", "Ladybug", "Starfish",
]
_CUTE_EMOJI = ["🌸", "✨", "🌟", "🧁", "🍭", "🐣", "🌈", "💫", "🌼", "🍬"]


def define(word):
    """Real dictionary definition via dictionaryapi.dev (no key)."""
    try:
        q = urllib.parse.quote(word)
        d = _get_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{q}")
    except Exception:  # noqa: BLE001
        return f"No definition found for '{word}'."
    if not isinstance(d, list) or not d:
        return f"No definition found for '{word}'."
    entry = d[0]
    parts = [f"📖 {entry.get('word', word)}"]
    for meaning in entry.get("meanings", [])[:2]:
        pos = meaning.get("partOfSpeech", "")
        defs = meaning.get("definitions", [])
        if defs:
            parts.append(f"({pos}) {defs[0].get('definition', '')}")
    return "\n".join(parts)


# Fancy unicode fonts for !font
_FONT_MAP = {
    "bold": (0x1D400, 0x1D41A),      # 𝐀 / 𝐚
    "italic": (0x1D434, 0x1D44E),    # 𝐴 / 𝑎
    "script": (0x1D49C, 0x1D4B6),    # 𝒜 / 𝒶
    "double": (0x1D538, 0x1D552),    # 𝔸 / 𝕒
    "mono": (0x1D670, 0x1D68A),      # 𝙰 / 𝚊
    "sans": (0x1D5A0, 0x1D5BA),      # 𝖠 / 𝖺
}


def fancy_text(style, text):
    style = style.lower()
    if style not in _FONT_MAP:
        return "Styles: " + ", ".join(_FONT_MAP)
    up, low = _FONT_MAP[style]
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(up + (ord(ch) - 65)))
        elif "a" <= ch <= "z":
            out.append(chr(low + (ord(ch) - 97)))
        else:
            out.append(ch)
    return "".join(out)


def cute_name():
    return random.choice(_CUTE_NAMES)


def cute_emoji():
    return random.choice(_CUTE_EMOJI)


def parse_duration(s):
    """'10m' / '30s' / '2h' / '1d' -> seconds. Bare number = minutes."""
    import re as _re
    m = _re.fullmatch(r"(\d+)\s*([smhd]?)", (s or "").strip().lower())
    if not m:
        return None
    n = int(m.group(1))
    return n * {"s": 1, "": 60, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def ship_percent(a, b):
    import hashlib
    key = "".join(sorted([a.lower(), b.lower()]))
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % 101


# --------------------------------------------------------------------- calc -
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("bad constant")
    if isinstance(node, ast.BinOp):
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


def calc(expr):
    try:
        return f"{expr} = {_safe_eval(ast.parse(expr, mode='eval').body)}"
    except Exception:
        return "Invalid expression. Example: !calc 2 * (3 + 4)"
