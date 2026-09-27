"""Durable, atomic daily quotas for AI image generation."""

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    remaining: int | None
    reason: str = ""
    retry_after: int = 0
    reservation_id: int | None = None


class ImageQuotaStore:
    def __init__(self, database_file, daily_limit, user_daily_limit, cooldown_seconds):
        self.database_file = database_file
        self.daily_limit = daily_limit
        self.user_daily_limit = user_daily_limit
        self.cooldown_seconds = cooldown_seconds
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS image_generations (
                    id INTEGER PRIMARY KEY,
                    utc_day TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'submitted'
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS image_generations_day
                ON image_generations (utc_day)
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS image_generations_user_day
                ON image_generations (user_id, utc_day)
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS image_generation_closed_days (
                    utc_day TEXT PRIMARY KEY
                )
            """)

    @staticmethod
    def _now(value):
        now = value or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _decision(self, connection, user_id, now, unlimited=False):
        day = now.date().isoformat()
        user_id = str(user_id)
        closed = connection.execute(
            "SELECT 1 FROM image_generation_closed_days WHERE utc_day=?", (day,)
        ).fetchone()
        if closed:
            return QuotaDecision(False, None, "global_limit")
        if unlimited:
            return QuotaDecision(True, None)
        user_count = connection.execute(
            "SELECT COUNT(*) FROM image_generations WHERE utc_day=? AND user_id=?",
            (day, user_id),
        ).fetchone()[0]
        remaining = max(0, self.user_daily_limit - user_count)
        if user_count >= self.user_daily_limit:
            return QuotaDecision(False, 0, "user_limit")

        last = connection.execute(
            """SELECT submitted_at FROM image_generations
               WHERE utc_day=? AND user_id=? ORDER BY id DESC LIMIT 1""",
            (day, user_id),
        ).fetchone()
        if last and self.cooldown_seconds:
            elapsed = (now - datetime.fromisoformat(last[0])).total_seconds()
            if elapsed < self.cooldown_seconds:
                return QuotaDecision(
                    False, remaining, "cooldown",
                    max(1, math.ceil(self.cooldown_seconds - elapsed)),
                )

        total = connection.execute(
            "SELECT COUNT(*) FROM image_generations WHERE utc_day=?", (day,)
        ).fetchone()[0]
        if total >= self.daily_limit:
            return QuotaDecision(False, None, "global_limit")
        return QuotaDecision(True, remaining)

    def check(self, user_id, now=None, unlimited=False):
        now = self._now(now)
        with self._connect() as connection:
            return self._decision(connection, user_id, now, unlimited)

    def reserve(self, user_id, room_id, now=None, unlimited=False):
        now = self._now(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            decision = self._decision(connection, user_id, now, unlimited)
            if not decision.allowed:
                connection.rollback()
                return decision
            cursor = connection.execute(
                """INSERT INTO image_generations
                   (utc_day, user_id, room_id, submitted_at, status)
                   VALUES (?, ?, ?, ?, 'submitted')""",
                (now.date().isoformat(), str(user_id), str(room_id), now.isoformat()),
            )
            connection.commit()
            return QuotaDecision(
                True,
                None if decision.remaining is None else decision.remaining - 1,
                reservation_id=cursor.lastrowid,
            )
        finally:
            connection.close()

    def finish(self, reservation_id, status):
        allowed = {"success", "cloudflare_error", "rejected", "timeout", "upload_error"}
        if status not in allowed:
            raise ValueError("invalid image generation status")
        with self._connect() as connection:
            connection.execute(
                "UPDATE image_generations SET status=? WHERE id=?",
                (status, reservation_id),
            )

    def close_day(self, now=None):
        day = self._now(now).date().isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO image_generation_closed_days (utc_day) VALUES (?)",
                (day,),
            )

    def submitted_count(self, user_id, day=None):
        utc_day = (day or datetime.now(timezone.utc).date())
        if isinstance(utc_day, date):
            utc_day = utc_day.isoformat()
        with self._connect() as connection:
            if user_id is None:
                row = connection.execute(
                    "SELECT COUNT(*) FROM image_generations WHERE utc_day=?", (utc_day,)
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT COUNT(*) FROM image_generations
                       WHERE utc_day=? AND user_id=?""",
                    (utc_day, str(user_id)),
                ).fetchone()
        return row[0]
