#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slap game: cross-room hand-raising duels with XP and win streaks.

Mechanics (per the spec):
  * A user does !slap. If nobody has a hand up, THEY raise their hand and wait
    for a target (works across all rooms the bot is in).
  * If someone else already has a hand up, the two have a slap fight; a random
    winner is chosen. The result is announced in BOTH players' rooms.
  * The winner gains XP (base * their current win streak); the loser loses XP
    (floored at 0) and their streak resets.
  * A user can only have ONE hand raised at a time. Trying again (same or other
    room) tells them their hand is already up.

State is persisted so XP/streaks survive restarts. The bot layer handles all
messaging/images; this module owns game state + scoring only.
"""

import copy
import json
import os
import random
import tempfile
import threading
import time
from contextlib import contextmanager

import fcntl

DATA_FILE = os.environ.get(
    "TALKINCHAT_SLAP_FILE",
    os.path.join(
        os.environ.get("TALKINCHAT_STATE_DIR", "/var/lib/talkinchat-bot"),
        "slap_data.json",
    ))

WIN_BASE = 10000     # winner gains WIN_BASE * current_streak
LOSS_BASE = 5000     # loser loses this (floored at 0)

SPIN_COOLDOWN = 45   # seconds between spins per user
MAX_HEALTH = 100
HEALTH_PER_MINUTE = 10
FIGHT_MIN_HEALTH = 10
NORMAL_DAMAGE = 10
CRITICAL_DAMAGE = 50
CRITICAL_CHANCE = 0.10
ARMOR_COST = 1_000_000

# (emoji, name, xp value, weight)  — higher weight = more common.
GIFTS = [
    ("🌹", "a Rose", 500, 26),
    ("🍫", "Chocolate", 500, 24),
    ("🧸", "a Teddy Bear", 1000, 20),
    ("🪙", "1,000 coins", 1000, 20),
    ("👛", "a Wallet", 5000, 12),
    ("💍", "a Ring", 8000, 8),
    ("💵", "a stack of Money", 10000, 8),
    ("💰", "10,000 coins", 10000, 6),
    ("💎", "a Diamond", 25000, 4),
    ("🚗", "a Car", 50000, 3),
    ("🏠", "a House", 100000, 1),      # very rare
    ("🏆", "100,000 coins", 100000, 1),  # very rare
]

_data = {}           # username(lower) -> {username,xp,streak,wins,losses,userid}
_pending = None      # {"user","userid","roomid","avatar","t"} or None
_spin_cd = {}        # username(lower) -> last spin timestamp
_award_lock = threading.RLock()


def _load():
    global _data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            _data = json.load(fh)
    except (FileNotFoundError, ValueError):
        _data = {}


def _save():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(_data, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"[slap] save failed: {exc}")


def _rec(username):
    key = username.lower()
    return _data.setdefault(key, {
        "username": username, "xp": 0, "streak": 0,
        "wins": 0, "losses": 0, "userid": None})


def _health_record(rec, now):
    try:
        value = int(rec.get("health", MAX_HEALTH))
    except (TypeError, ValueError):
        value = MAX_HEALTH
    value = max(0, min(MAX_HEALTH, value))
    try:
        updated = float(rec.get("health_updated_at", now))
    except (TypeError, ValueError):
        updated = now
    if updated < 0 or updated > now:
        updated = now
    minutes = max(0, int((now - updated) // 60))
    if minutes:
        value = min(MAX_HEALTH, value + minutes * HEALTH_PER_MINUTE)
        updated = now if value == MAX_HEALTH else updated + minutes * 60
    rec["health"] = value
    rec["health_updated_at"] = updated
    rec["armor"] = bool(rec.get("armor", False))
    return rec


def health(username, now=None):
    now = time.time() if now is None else float(now)
    rec = _health_record(_rec(username), now)
    return {
        "health": rec["health"],
        "health_updated_at": rec["health_updated_at"],
        "armor": rec["armor"],
        "shielded": rec.get("shield_until", 0) > now,
    }


def seconds_until_fight_ready(username, now=None):
    now = time.time() if now is None else float(now)
    status = health(username, now)
    if status["health"] >= FIGHT_MIN_HEALTH:
        return 0
    elapsed = max(0, now - status["health_updated_at"])
    return max(1, int(60 - elapsed % 60))


def apply_slap_damage(username, critical=False, now=None):
    now = time.time() if now is None else float(now)
    rec = _health_record(_rec(username), now)
    base = CRITICAL_DAMAGE if critical else NORMAL_DAMAGE
    blocked = rec.get("shield_until", 0) > now
    damage = 0 if blocked else (base // 2 if rec.get("armor") else base)
    rec["health"] = max(0, rec["health"] - damage)
    rec["health_updated_at"] = now
    return {
        "base_damage": base,
        "damage": damage,
        "health": rec["health"],
        "blocked": blocked,
        "armor": rec.get("armor", False),
    }


def add_xp(username, userid, amount):
    """Shared XP hook for all games. Returns the user's new total (floored at 0)."""
    rec = _rec(username)
    rec["username"] = username
    if userid is not None:
        rec["userid"] = userid
    rec["xp"] = max(0, rec["xp"] + amount)
    _save()
    return rec["xp"]


@contextmanager
def _award_file_lock():
    lock_path = f"{DATA_FILE}.lock"
    os.makedirs(os.path.dirname(os.path.abspath(DATA_FILE)), exist_ok=True)
    with _award_lock:
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_award_data():
    if not os.path.exists(DATA_FILE):
        return copy.deepcopy(_data)
    with open(DATA_FILE, "r", encoding="utf-8") as data_file:
        data = json.load(data_file)
    if not isinstance(data, dict) or any(not isinstance(item, dict) for item in data.values()):
        raise ValueError("slap data is malformed")
    return data


def _write_award_data(data):
    directory = os.path.dirname(os.path.abspath(DATA_FILE))
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(DATA_FILE)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as data_file:
            json.dump(
                data, data_file, indent=2, ensure_ascii=False,
                sort_keys=True, allow_nan=False,
            )
            data_file.flush()
            os.fsync(data_file.fileno())
        os.replace(temporary_path, DATA_FILE)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def add_xp_once(username, userid, amount, award_key):
    """Atomically apply one stable XP award at most once."""
    global _data
    username = str(username).strip()
    award_key = str(award_key).strip()
    if not username or not award_key:
        raise ValueError("username and award_key are required")

    with _award_file_lock():
        candidate = _read_award_data()
        key = username.lower()
        record = candidate.setdefault(key, {
            "username": username, "xp": 0, "streak": 0,
            "wins": 0, "losses": 0, "userid": None,
        })
        award_keys = record.setdefault("award_keys", [])
        if not isinstance(award_keys, list) or any(
            not isinstance(item, str) for item in award_keys
        ):
            raise ValueError("slap award keys are malformed")
        if award_key in award_keys:
            _data = candidate
            return {"applied": False, "xp": record.get("xp", 0)}

        record["username"] = username
        if userid is not None:
            record["userid"] = userid
        record["xp"] = max(0, record.get("xp", 0) + amount)
        award_keys.append(award_key)
        _write_award_data(candidate)
        _data = candidate
        return {"applied": True, "xp": record["xp"]}


def get_xp(username):
    rec = _data.get(username.lower())
    return rec["xp"] if rec else 0


# ---------------------------------------------------------------- shields ----
# Bomb shields: pay XP to be immune to ,bomb for a while. Stored on the user
# record (shield_until = epoch seconds) so it persists across restarts.
SHIELD_PLANS = {           # plan -> (seconds, XP cost)
    "1h": (3600, 8_000),
    "24h": (86_400, 50_000),
}


def market_items():
    return [
        {"id": "armor", "name": "Permanent Armor", "cost": ARMOR_COST,
         "description": "Halves slap damage forever"},
        {"id": "shield-1h", "name": "1 Hour Shield", "cost": SHIELD_PLANS["1h"][1],
         "description": "Blocks bombs and slap damage for 1 hour"},
        {"id": "shield-24h", "name": "24 Hour Shield", "cost": SHIELD_PLANS["24h"][1],
         "description": "Blocks bombs and slap damage for 24 hours"},
    ]


def buy_item(username, userid, item, now=None):
    item = (item or "").lower()
    now = time.time() if now is None else float(now)
    rec = _rec(username)
    if item == "armor":
        if rec.get("armor"):
            return {"ok": False, "error": "owned"}
        cost = ARMOR_COST
        if rec.get("xp", 0) < cost:
            return {"ok": False, "error": "xp", "cost": cost}
        rec["xp"] -= cost
        rec["armor"] = True
    elif item in {"shield-1h", "shield-24h"}:
        plan = item.removeprefix("shield-")
        seconds, cost = SHIELD_PLANS[plan]
        if rec.get("xp", 0) < cost:
            return {"ok": False, "error": "xp", "cost": cost}
        rec["xp"] -= cost
        rec["shield_until"] = max(now, rec.get("shield_until", 0)) + seconds
    else:
        return {"ok": False, "error": "item"}
    rec["username"] = username
    if userid is not None:
        rec["userid"] = userid
    _save()
    return {"ok": True, "item": item, "xp": rec["xp"]}


def buy_shield(username, userid, plan):
    """Returns (True, expiry_epoch) on success, or (False, reason) where reason
    is 'plan' (unknown plan) or an int XP cost (couldn't afford)."""
    plan = (plan or "").lower()
    if plan not in SHIELD_PLANS:
        return (False, "plan")
    result = buy_item(username, userid, f"shield-{plan}")
    if not result["ok"]:
        return (False, result.get("cost", "plan"))
    return (True, _rec(username)["shield_until"])


def is_shielded(username):
    rec = _data.get((username or "").lower())
    return bool(rec and rec.get("shield_until", 0) > time.time())


def shield_left(username):
    """Seconds of shield remaining (0 if none)."""
    rec = _data.get((username or "").lower())
    if not rec:
        return 0
    return max(0, int(rec.get("shield_until", 0) - time.time()))


# ------------------------------------------------------------------ ranks ----
RANKS = [
    (0, "🥚 Newbie"), (10_000, "🐣 Rookie"), (50_000, "🎖️ Regular"),
    (150_000, "⭐ Star"), (400_000, "🔥 Elite"), (1_000_000, "💎 Master"),
    (3_000_000, "👑 Legend"), (10_000_000, "🏆 Mythic"),
]


def rank_for(xp):
    title = RANKS[0][1]
    for threshold, name in RANKS:
        if xp >= threshold:
            title = name
        else:
            break
    return title


def rank_progress(xp):
    """Return (rank, next_rank_name, xp_into, xp_needed) for a progress bar."""
    cur = RANKS[0]
    nxt = None
    for i, (threshold, name) in enumerate(RANKS):
        if xp >= threshold:
            cur = (threshold, name)
            nxt = RANKS[i + 1] if i + 1 < len(RANKS) else None
        else:
            break
    if not nxt:
        return cur[1], None, 0, 0
    return cur[1], nxt[1], xp - cur[0], nxt[0] - cur[0]


# ------------------------------------------------------------------ daily ----
DAILY_BASE = 5000
DAILY_COOLDOWN = 20 * 3600      # 20 hours


def claim_daily(username, userid):
    rec = _rec(username)
    rec["username"] = username
    rec["userid"] = userid
    now = time.time()
    last = rec.get("daily_last", 0)
    if now - last < DAILY_COOLDOWN:
        return {"ok": False, "wait": int(DAILY_COOLDOWN - (now - last))}
    # streak: within 44h keeps it, else resets
    streak = rec.get("daily_streak", 0) + 1 if now - last < 44 * 3600 else 1
    amount = DAILY_BASE * min(streak, 10)
    rec["daily_last"] = now
    rec["daily_streak"] = streak
    rec["xp"] = rec["xp"] + amount
    _save()
    return {"ok": True, "amount": amount, "streak": streak, "xp": rec["xp"]}


# --------------------------------------------------------------- transfer ----
def transfer(from_user, from_uid, to_user, amount):
    if amount <= 0:
        return {"ok": False, "error": "Amount must be positive."}
    src = _rec(from_user)
    if src["xp"] < amount:
        return {"ok": False, "error": f"You only have {src['xp']:,} XP."}
    dst = _rec(to_user)
    src["xp"] -= amount
    dst["xp"] += amount
    src["userid"] = from_uid
    dst["username"] = to_user
    _save()
    return {"ok": True, "amount": amount, "from_xp": src["xp"], "to": dst["username"]}


# -------------------------------------------------------------------- rep ----
_rep_cd = {}


def add_rep(from_user, to_user):
    if from_user.lower() == to_user.lower():
        return {"ok": False, "error": "You can't rep yourself!"}
    now = time.time()
    if now - _rep_cd.get(from_user.lower(), 0) < 3600:
        return {"ok": False, "wait": int(3600 - (now - _rep_cd.get(from_user.lower(), 0)))}
    _rep_cd[from_user.lower()] = now
    dst = _rec(to_user)
    dst["username"] = to_user
    dst["rep"] = dst.get("rep", 0) + 1
    _save()
    return {"ok": True, "rep": dst["rep"]}


def rep_leaderboard(n=10):
    rows = [r for r in _data.values() if r.get("rep", 0) > 0]
    return sorted(rows, key=lambda r: r.get("rep", 0), reverse=True)[:n]


# --------------------------------------------------------------- marriage ----
def marry(a_user, b_user):
    a, b = _rec(a_user), _rec(b_user)
    if a.get("spouse"):
        return {"ok": False, "error": f"You're already married to {a['spouse']}!"}
    if b.get("spouse"):
        return {"ok": False, "error": f"{b_user} is already married to {b['spouse']}!"}
    a["spouse"], b["spouse"] = b_user, a_user
    a["username"], b["username"] = a_user, b_user
    _save()
    return {"ok": True}


def divorce(user):
    rec = _rec(user)
    spouse = rec.get("spouse")
    if not spouse:
        return {"ok": False, "error": "You're not married."}
    rec["spouse"] = None
    srec = _data.get(spouse.lower())
    if srec:
        srec["spouse"] = None
    _save()
    return {"ok": True, "spouse": spouse}


def couples(n=10):
    seen, out = set(), []
    for r in _data.values():
        sp = r.get("spouse")
        u = r.get("username", "")
        if sp and u and u.lower() not in seen and sp.lower() not in seen:
            seen.add(u.lower()); seen.add(sp.lower())
            out.append((u, sp))
    return out[:n]


def stats(username):
    return _data.get(username.lower())


def leaderboard(n=10):
    rows = sorted(_data.values(), key=lambda r: r.get("xp", 0), reverse=True)
    return rows[:n]


def pending():
    return _pending


def slap(user, userid, roomid, avatar, now=None):
    """Play one immediate slap round against the bot."""
    global _pending
    now = time.time() if now is None else float(now)

    current = health(user, now)
    if current["health"] < FIGHT_MIN_HEALTH:
        return {"action": "health", "health": current["health"],
                "wait": seconds_until_fight_ready(user, now)}

    _pending = None
    human = {"name": user, "userid": userid, "room": roomid, "avatar": avatar}
    bot = {"name": "TalkinChat Bot", "userid": "bot", "room": roomid, "avatar": ""}
    human_wins = random.randint(0, 1) == 0
    winner, loser = (human, bot) if human_wins else (bot, human)
    record = _rec(user)
    record["userid"] = userid
    record["username"] = user
    critical = random.random() < CRITICAL_CHANCE
    gained = lost = 0
    damage = {"base_damage": CRITICAL_DAMAGE if critical else NORMAL_DAMAGE,
              "damage": 0, "health": 100, "blocked": False, "armor": False}
    if human_wins:
        record["streak"] = record.get("streak", 0) + 1
        gained = WIN_BASE * record["streak"]
        record["xp"] += gained
        record["wins"] += 1
        damage["damage"] = damage["base_damage"]
        damage["health"] = max(0, 100 - damage["damage"])
    else:
        before = record["xp"]
        record["xp"] = max(0, record["xp"] - LOSS_BASE)
        lost = before - record["xp"]
        record["losses"] += 1
        record["streak"] = 0
        damage = apply_slap_damage(user, critical, now)
    _save()
    return {
        "action": "fight",
        "winner": {**winner, "xp": record["xp"] if human_wins else 0,
                   "streak": record["streak"] if human_wins else 0,
                   "health": health(user, now)["health"] if human_wins else 100},
        "loser": {**loser, "xp": record["xp"] if not human_wins else 0,
                  "health": damage["health"]},
        "gained": gained, "lost": lost, "streak": record["streak"],
        "critical": critical, **damage,
    }


def spin(user, userid):
    """Spin for a random gift; awards XP. Returns a result dict."""
    now = time.time()
    last = _spin_cd.get(user.lower(), 0)
    if now - last < SPIN_COOLDOWN:
        return {"action": "cooldown", "wait": int(SPIN_COOLDOWN - (now - last))}
    _spin_cd[user.lower()] = now

    emojis = [g[0] for g in GIFTS]
    names = [g[1] for g in GIFTS]
    values = [g[2] for g in GIFTS]
    weights = [g[3] for g in GIFTS]
    idx = random.choices(range(len(GIFTS)), weights=weights, k=1)[0]

    rec = _rec(user)
    rec["username"] = user
    rec["userid"] = userid
    rec["xp"] += values[idx]
    _save()
    rare = weights[idx] == 1
    return {"action": "spin", "emoji": emojis[idx], "name": names[idx],
            "value": values[idx], "xp": rec["xp"], "rare": rare}


_load()
