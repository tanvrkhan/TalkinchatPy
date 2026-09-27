#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data and pure logic for the bot's text games.

The engine (state, cross-room broadcasting, message watching) lives in bot.py;
this module only supplies questions/words and small generators. XP is awarded
through services.slap.add_xp so every game shares one economy.
"""

import random


def _bold(text):
    out = []
    for char in text:
        if "A" <= char <= "Z":
            out.append(chr(0x1D400 + ord(char) - ord("A")))
        elif "a" <= char <= "z":
            out.append(chr(0x1D41A + ord(char) - ord("a")))
        else:
            out.append(char)
    return "".join(out)


# --------------------------------------------------------------- bingo -----
def make_bingo_card(rng=None):
    """Return an immutable 75-ball Bingo card with a free center."""
    rng = rng or random
    columns = [rng.sample(range(start, start + 15), 5)
               for start in (1, 16, 31, 46, 61)]
    rows = [[columns[col][row] for col in range(5)] for row in range(5)]
    rows[2][2] = None
    return tuple(tuple(row) for row in rows)


def _bingo_lines(card):
    rows = [tuple(row) for row in card]
    columns = [tuple(card[row][col] for row in range(5)) for col in range(5)]
    diagonals = [tuple(card[i][i] for i in range(5)),
                 tuple(card[i][4 - i] for i in range(5))]
    return rows + columns + diagonals


def _marked(value, called):
    return value is None or value in called


def bingo_has_won(card, called):
    called = set(called)
    return any(all(_marked(value, called) for value in line)
               for line in _bingo_lines(card))


def bingo_progress(card, called):
    called = set(called)
    marked = max(sum(_marked(value, called) for value in line)
                 for line in _bingo_lines(card))
    return marked, 5


def bingo_has_blackout(card, called):
    """Return True when every numbered square on the card has been called."""
    called = set(called)
    return all(_marked(value, called) for row in card for value in row)


BINGO_MARKERS = ("🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "⚫", "⚪")
_MONO_DIGITS = str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")


def _bingo_number(value):
    return f"{value:02d}".translate(_MONO_DIGITS)


def render_bingo_card(card, called, title="Your Bingo Card", marker="🔴"):
    called = set(called)
    divider = " "
    headers = tuple("ＢＩＮＧＯ")
    lines = [f"🎟️ {_bold(title)}", "", divider.join(headers)]
    for row in card:
        cells = []
        for value in row:
            if value is None:
                cells.append("⭐")
            elif value in called:
                cells.append(marker)
            else:
                cells.append(_bingo_number(value))
        lines.append(divider.join(cells))
    marked, total = bingo_progress(card, called)
    lines.extend(["", f"Progress: {marked}/{total}"])
    return "\n".join(lines)

# ------------------------------------------------------------ dictionary ----
# For word-chain validation. Loaded from the system word list if present
# (apt install wamerican -> /usr/share/dict/words). If none is found, is_word
# returns True so the game still runs (just without validation).
_WORDS = set()


def _load_words():
    for path in ("/usr/share/dict/words", "/usr/share/dict/american-english",
                 "/usr/share/dict/british-english"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    w = line.strip().lower()
                    if w.isalpha() and len(w) >= 2:
                        _WORDS.add(w)
            if _WORDS:
                break
        except OSError:
            continue


def is_word(word):
    if not _WORDS:
        return True                     # no dictionary available -> don't block
    return word.lower() in _WORDS


_load_words()

# ---------------------------------------------------------------- trivia ----
TRIVIA = [
    ("What is the capital of France?", ["paris"]),
    ("What is the capital of Japan?", ["tokyo"]),
    ("What is the capital of Pakistan?", ["islamabad"]),
    ("How many continents are there?", ["7", "seven"]),
    ("What planet is known as the Red Planet?", ["mars"]),
    ("What is the largest ocean?", ["pacific"]),
    ("What is the chemical symbol for gold?", ["au"]),
    ("How many legs does a spider have?", ["8", "eight"]),
    ("What is the tallest mountain on Earth?", ["everest", "mount everest"]),
    ("What color do you get mixing blue and yellow?", ["green"]),
    ("How many days are in a leap year?", ["366"]),
    ("What is the fastest land animal?", ["cheetah"]),
    ("What gas do plants absorb from the air?", ["carbon dioxide", "co2"]),
    ("What is the smallest prime number?", ["2", "two"]),
    ("Who painted the Mona Lisa?", ["da vinci", "leonardo da vinci", "leonardo"]),
    ("What is the currency of Japan?", ["yen"]),
    ("How many players are on a soccer team on the field?", ["11", "eleven"]),
    ("What is the hardest natural substance?", ["diamond"]),
    ("What is the largest planet in our solar system?", ["jupiter"]),
    ("What is frozen water called?", ["ice"]),
    ("What language has the most native speakers?", ["mandarin", "chinese", "mandarin chinese"]),
    ("How many sides does a hexagon have?", ["6", "six"]),
    ("What is the capital of Italy?", ["rome"]),
    ("What organ pumps blood through the body?", ["heart"]),
    ("What is the boiling point of water in Celsius?", ["100"]),
    ("Which is the longest river in the world?", ["nile", "amazon"]),
    ("What do bees make?", ["honey"]),
    ("What is the national animal of Pakistan?", ["markhor"]),
    ("How many colors are in a rainbow?", ["7", "seven"]),
    ("What is the square root of 144?", ["12", "twelve"]),
]

# --------------------------------------------------------------- hangman ----
HANGMAN_RIDDLES = (
    ("shadow", "I follow you in light but vanish in darkness. What am I?"),
    ("keyboard", "I have keys but no locks, and space but no rooms. What am I?"),
    ("echo", "I speak without a mouth and answer without ears. What am I?"),
    ("clock", "I have a face and two hands, but no arms or legs. What am I?"),
    ("river", "I run all day but never walk, and I have a bed but never sleep. What am I?"),
    ("candle", "The more I work, the shorter I grow. What am I?"),
    ("cloud", "I float without wings and sometimes cry without eyes. What am I?"),
    ("piano", "I have many keys, but I cannot open a single door. What am I?"),
    ("map", "I show cities without houses and oceans without water. What am I?"),
    ("book", "I hold many stories but never speak a word. What am I?"),
    ("silence", "Say my name and I disappear. What am I?"),
    ("rainbow", "I wear many colors and appear after rain. What am I?"),
    ("mirror", "I copy everything before me but keep nothing. What am I?"),
    ("needle", "I have one eye but cannot see. What am I?"),
    ("stamp", "I travel around the world while staying in one corner. What am I?"),
    ("towel", "I become wetter the more I dry. What am I?"),
    ("bottle", "I have a neck but no head. What am I?"),
    ("fire", "Feed me and I live; give me a drink and I die. What am I?"),
    ("moon", "I change my shape but never leave the sky. What am I?"),
    ("footsteps", "The more you take, the more you leave behind. What am I?"),
)


# --------------------------------------------------------------- scramble ---
SCRAMBLE_WORDS = [
    "talkinchat", "python", "chatroom", "rainbow", "diamond", "internet", "keyboard",
    "elephant", "mountain", "guitar", "pyramid", "octopus", "volcano", "penguin",
    "sandwich", "umbrella", "computer", "birthday", "chocolate", "adventure",
    "butterfly", "dinosaur", "galaxy", "treasure", "whisper", "monster", "jungle",
    "lantern", "cactus", "dolphin", "wizard", "compass", "harbor", "meadow",
    "puzzle", "rocket", "castle", "thunder", "island", "market",
]

# ---------------------------------------------------------------- emoji ------
EMOJI = [
    ("🦁👑", ["lion king", "the lion king"]),
    ("🕷️🕸️👦", ["spiderman", "spider man"]),
    ("❄️⛄👸", ["frozen"]),
    ("🐭🏰", ["disney", "mickey mouse"]),
    ("🍫🏭", ["charlie and the chocolate factory", "chocolate factory"]),
    ("🐠🔍", ["finding nemo"]),
    ("🚗⚡👦", ["cars"]),
    ("👻🚫", ["ghostbusters"]),
    ("🦇🧑", ["batman"]),
    ("🌊🧜‍♀️", ["the little mermaid", "little mermaid"]),
    ("🐝🎬", ["bee movie"]),
    ("🧸🤠🚀", ["toy story"]),
    ("🐼🥋", ["kung fu panda"]),
    ("💍🌋", ["lord of the rings"]),
    ("🦖🏞️", ["jurassic park"]),
    ("🤖❤️", ["wall-e", "walle"]),
    ("🧙⚡", ["harry potter"]),
    ("👽📞🏠", ["et", "e.t."]),
    ("🐧🎩", ["batman returns", "penguin"]),
    ("🍕🐀", ["ratatouille"]),
]

# ----------------------------------------------------------- fastest finger -
FF_PHRASES = [
    "the quick brown fox jumps",
    "talkinchat is the best chat app",
    "type this as fast as you can",
    "practice makes a man perfect",
    "a rolling stone gathers no moss",
    "better late than never today",
    "actions speak louder than words",
    "every cloud has a silver lining",
    "the early bird catches the worm",
    "honesty is the best policy always",
    "curiosity killed the cat quickly",
    "birds of a feather flock together",
    "an apple a day keeps illness away",
    "slow and steady wins the race",
]

# ------------------------------------------------------- would you rather ----
WYR = [
    ("Be able to fly", "Be invisible"),
    ("Have unlimited money", "Have unlimited time"),
    ("Live in space", "Live under the sea"),
    ("Only be able to whisper", "Only be able to shout"),
    ("Have super strength", "Have super speed"),
    ("Read minds", "See the future"),
    ("Never use social media again", "Never watch movies again"),
    ("Be a famous singer", "Be a famous actor"),
    ("Always be 10 minutes late", "Always be 20 minutes early"),
    ("Have a pet dragon", "Have a pet unicorn"),
    ("Eat only sweet food forever", "Eat only spicy food forever"),
    ("Travel to the past", "Travel to the future"),
    ("Be the funniest person", "Be the smartest person"),
    ("Have no phone for a month", "Have no music for a month"),
]


# ---------------------------------------------------------------- helpers ----
def pick_trivia():
    q, answers = random.choice(TRIVIA)
    return q, answers


def scramble():
    word = random.choice(SCRAMBLE_WORDS)
    letters = list(word)
    while True:
        random.shuffle(letters)
        if "".join(letters) != word:
            break
    return " ".join(letters).upper(), word


def pick_emoji():
    puzzle, answers = random.choice(EMOJI)
    return puzzle, answers


def pick_ff():
    return random.choice(FF_PHRASES)


def pick_wyr():
    return random.choice(WYR)


# --------------------------------------------------- find the vampire words --
VAMPIRE_WORDS = [
    "Pizza", "Beach", "School", "Doctor", "Football", "Winter", "Coffee",
    "Airport", "Wedding", "Library", "Hospital", "Rainbow", "Guitar", "Mountain",
    "Ocean", "Birthday", "Chocolate", "Elephant", "Police", "Garden", "Cinema",
    "Kitchen", "Soldier", "Painter", "Island", "Circus", "Dragon", "Castle",
    "Robot", "Pirate", "Astronaut", "Teacher", "Farmer", "Snowman", "Volcano",
    "Desert", "Jungle", "Spaceship", "Wizard", "Waterfall", "Camera", "Bakery",
    "Zombie", "Football", "Sunset", "Diamond", "Umbrella", "Lighthouse",
]


def pick_vampire_word():
    return random.choice(VAMPIRE_WORDS)


def gen_math():
    """Small DMAS equation with an integer answer. Returns (expr, answer_str)."""
    import operator
    ops = [("+", operator.add), ("-", operator.sub), ("*", operator.mul)]
    for _ in range(50):
        a, b, c = (random.randint(2, 12) for _ in range(3))
        (o1s, o1f), (o2s, o2f) = random.choice(ops), random.choice(ops)
        # evaluate with correct precedence (* before + -)
        if o1s == "*" and o2s != "*":
            val = o2f(o1f(a, b), c)
        elif o2s == "*" and o1s != "*":
            val = o1f(a, o2f(b, c))
        elif o1s == "*" and o2s == "*":
            val = a * b * c
        else:  # left to right for + and -
            val = o2f(o1f(a, b), c)
        if -50 <= val <= 200:
            return f"{a} {o1s} {b} {o2s} {c}", str(val)
    return "2 + 3 * 4", "14"
