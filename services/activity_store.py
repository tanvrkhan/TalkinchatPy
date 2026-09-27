"""Shared durable storage for public room activity and bot audit data."""

import json
import os
import sqlite3
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityEntry:
    kind: str
    occurred_at: float
    user_id: str
    username: str
    text: str = ""
    room_id: str = ""


@dataclass(frozen=True)
class RoomReportPage:
    entries: list[ActivityEntry]
    message_count: int
    join_count: int
    leave_count: int
    unique_speakers: int
    active_users: int
    admin_action_count: int
    total_entries: int


@dataclass(frozen=True)
class AdminActionEntry:
    occurred_at: float
    actor_id: str
    actor_name: str
    target_id: str
    target_name: str
    action: str
    outcome: str
    detail: str


@dataclass(frozen=True)
class AdminLogPage:
    entries: list[AdminActionEntry]
    total_entries: int


class ActivityStore:
    def __init__(self, database_file, now=time.time):
        self.database_file = database_file
        self._clock = now
        directory = os.path.dirname(os.path.abspath(database_file))
        os.makedirs(directory, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rooms (
                    room_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    event_key TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    text TEXT NOT NULL,
                    occurred_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_room_time
                    ON messages (room_id, occurred_at);
                CREATE INDEX IF NOT EXISTS messages_user_time
                    ON messages (user_id, occurred_at);
                CREATE TABLE IF NOT EXISTS presence_events (
                    event_key TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    event TEXT NOT NULL CHECK(event IN ('join', 'leave')),
                    occurred_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS presence_room_time
                    ON presence_events (room_id, occurred_at);
                CREATE TABLE IF NOT EXISTS last_activity (
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    PRIMARY KEY (room_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS admin_actions (
                    event_key TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    occurred_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS admin_actions_room_time
                    ON admin_actions (room_id, occurred_at);
                CREATE TABLE IF NOT EXISTS ai_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)

    @staticmethod
    def _id(value):
        return str(value)

    def record_room(self, room_id, name, occurred_at=None):
        occurred_at = float(self._clock() if occurred_at is None else occurred_at)
        with self._connect() as db:
            db.execute(
                """INSERT INTO rooms (room_id, name, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(room_id) DO UPDATE SET
                   name=excluded.name, updated_at=excluded.updated_at""",
                (self._id(room_id), str(name or ""), occurred_at),
            )

    def record_user(self, user_id, username, occurred_at=None):
        occurred_at = float(self._clock() if occurred_at is None else occurred_at)
        with self._connect() as db:
            db.execute(
                """INSERT INTO users (user_id, username, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username, updated_at=excluded.updated_at""",
                (self._id(user_id), str(username or ""), occurred_at),
            )

    def room_name(self, room_id):
        with self._connect() as db:
            row = db.execute("SELECT name FROM rooms WHERE room_id=?",
                             (self._id(room_id),)).fetchone()
        return row[0] if row else None

    def _record_identity(self, db, room_id, room_name, user_id, username, occurred_at):
        db.execute(
            """INSERT INTO rooms (room_id, name, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(room_id) DO UPDATE SET
               name=excluded.name, updated_at=MAX(rooms.updated_at, excluded.updated_at)""",
            (room_id, str(room_name or ""), occurred_at),
        )
        db.execute(
            """INSERT INTO users (user_id, username, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
               username=excluded.username, updated_at=MAX(users.updated_at, excluded.updated_at)""",
            (user_id, str(username or ""), occurred_at),
        )

    def _update_last(self, db, room_id, user_id, username, kind, occurred_at):
        db.execute(
            """INSERT INTO last_activity
               (room_id, user_id, username, kind, occurred_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(room_id, user_id) DO UPDATE SET
               username=excluded.username, kind=excluded.kind,
               occurred_at=excluded.occurred_at
               WHERE excluded.occurred_at >= last_activity.occurred_at""",
            (room_id, user_id, str(username or ""), kind, occurred_at),
        )

    def record_message(self, event_key, room_id, room_name, user_id, username,
                       text, occurred_at=None):
        occurred_at = float(self._clock() if occurred_at is None else occurred_at)
        room_id, user_id = self._id(room_id), self._id(user_id)
        with self._connect() as db:
            self._record_identity(db, room_id, room_name, user_id, username, occurred_at)
            cursor = db.execute(
                """INSERT OR IGNORE INTO messages
                   (event_key, room_id, user_id, username, text, occurred_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(event_key), room_id, user_id, str(username or ""),
                 str(text or ""), occurred_at),
            )
            if cursor.rowcount:
                self._update_last(db, room_id, user_id, username, "message", occurred_at)
        return bool(cursor.rowcount)

    def record_presence(self, event_key, room_id, room_name, user_id, username,
                        event, occurred_at=None):
        if event not in {"join", "leave"}:
            raise ValueError("presence event must be join or leave")
        occurred_at = float(self._clock() if occurred_at is None else occurred_at)
        room_id, user_id = self._id(room_id), self._id(user_id)
        with self._connect() as db:
            self._record_identity(db, room_id, room_name, user_id, username, occurred_at)
            cursor = db.execute(
                """INSERT OR IGNORE INTO presence_events
                   (event_key, room_id, user_id, username, event, occurred_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(event_key), room_id, user_id, str(username or ""), event, occurred_at),
            )
            if cursor.rowcount:
                self._update_last(db, room_id, user_id, username, event, occurred_at)
        return bool(cursor.rowcount)

    def record_admin_action(self, event_key, room_id, room_name, actor_id,
                            actor_name, target_id, target_name, action, outcome,
                            detail="", occurred_at=None):
        occurred_at = float(self._clock() if occurred_at is None else occurred_at)
        room_id = self._id(room_id)
        self.record_room(room_id, room_name, occurred_at)
        with self._connect() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO admin_actions
                   (event_key, room_id, actor_id, actor_name, target_id, target_name,
                    action, outcome, detail, occurred_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(event_key), room_id, self._id(actor_id), str(actor_name or ""),
                 self._id(target_id or ""), str(target_name or ""), str(action),
                 str(outcome), str(detail or ""), occurred_at),
            )
        return bool(cursor.rowcount)

    def room_report(self, room_id, since, limit=10, offset=0):
        room_id = self._id(room_id)
        params = (room_id, float(since))
        union = """
            SELECT 'message' kind, occurred_at, user_id, username, text
              FROM messages WHERE room_id=? AND occurred_at>=?
            UNION ALL
            SELECT event kind, occurred_at, user_id, username, '' text
              FROM presence_events WHERE room_id=? AND occurred_at>=?
        """
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM ({union}) ORDER BY occurred_at ASC LIMIT ? OFFSET ?",
                (*params, *params, int(limit), int(offset)),
            ).fetchall()
            counts = db.execute(
                """SELECT
                    (SELECT COUNT(*) FROM messages WHERE room_id=? AND occurred_at>=?),
                    (SELECT COUNT(*) FROM presence_events WHERE room_id=? AND event='join' AND occurred_at>=?),
                    (SELECT COUNT(*) FROM presence_events WHERE room_id=? AND event='leave' AND occurred_at>=?),
                    (SELECT COUNT(DISTINCT user_id) FROM messages WHERE room_id=? AND occurred_at>=?),
                    (SELECT COUNT(*) FROM last_activity WHERE room_id=? AND occurred_at>=?),
                    (SELECT COUNT(*) FROM admin_actions WHERE room_id=? AND occurred_at>=?)""",
                (*params, *params, *params, *params, *params, *params),
            ).fetchone()
        entries = [ActivityEntry(row["kind"], row["occurred_at"], row["user_id"],
                                 row["username"], row["text"], room_id) for row in rows]
        return RoomReportPage(entries, *counts, counts[0] + counts[1] + counts[2])

    def admin_log(self, room_id, limit=10, offset=0, since=0):
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM admin_actions WHERE room_id=? AND occurred_at>=?
                   ORDER BY occurred_at ASC LIMIT ? OFFSET ?""",
                (self._id(room_id), float(since), int(limit), int(offset)),
            ).fetchall()
            total = db.execute(
                "SELECT COUNT(*) FROM admin_actions WHERE room_id=? AND occurred_at>=?",
                (self._id(room_id), float(since)),
            ).fetchone()[0]
        return AdminLogPage([
            AdminActionEntry(row["occurred_at"], row["actor_id"], row["actor_name"],
                             row["target_id"], row["target_name"], row["action"],
                             row["outcome"], row["detail"])
            for row in rows
        ], total)

    def last_active(self, room_id, user_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM last_activity WHERE room_id=? AND user_id=?",
                (self._id(room_id), self._id(user_id)),
            ).fetchone()
        if not row:
            return None
        return ActivityEntry(row["kind"], row["occurred_at"], row["user_id"],
                             row["username"])

    def creator_search(self, query, limit=50, offset=0):
        with self._connect() as db:
            rows = db.execute(
                """SELECT 'message' kind, occurred_at, user_id, username, text, room_id
                   FROM messages WHERE text LIKE ? ESCAPE '\\'
                   ORDER BY occurred_at DESC LIMIT ? OFFSET ?""",
                (f"%{str(query)}%", int(limit), int(offset)),
            ).fetchall()
        return [ActivityEntry(row["kind"], row["occurred_at"], row["user_id"],
                              row["username"], row["text"], row["room_id"])
                for row in rows]

    def save_profile(self, user_id, profile, updated_at=None):
        updated_at = float(self._clock() if updated_at is None else updated_at)
        encoded = json.dumps(profile, ensure_ascii=True, separators=(",", ":"))
        with self._connect() as db:
            db.execute(
                """INSERT INTO ai_profiles (user_id, profile_json, updated_at)
                   VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
                   profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
                (self._id(user_id), encoded, updated_at),
            )

    def get_profile(self, user_id, max_age_seconds=30 * 86400):
        with self._connect() as db:
            row = db.execute("SELECT profile_json, updated_at FROM ai_profiles WHERE user_id=?",
                             (self._id(user_id),)).fetchone()
            if not row:
                return None
            if max_age_seconds is not None and row["updated_at"] < self._clock() - max_age_seconds:
                db.execute("DELETE FROM ai_profiles WHERE user_id=?", (self._id(user_id),))
                return None
        try:
            return json.loads(row["profile_json"])
        except (TypeError, ValueError):
            return None

    def cleanup(self, batch_size=500):
        now = float(self._clock())
        cutoffs = {
            "messages": now - 3 * 86400,
            "presence_events": now - 30 * 86400,
            "last_activity": now - 30 * 86400,
            "admin_actions": now - 30 * 86400,
            "ai_profiles": now - 30 * 86400,
        }
        with self._connect() as db:
            for table, cutoff in cutoffs.items():
                column = "updated_at" if table == "ai_profiles" else "occurred_at"
                db.execute(
                    f"DELETE FROM {table} WHERE rowid IN "
                    f"(SELECT rowid FROM {table} WHERE {column} < ? LIMIT ?)",
                    (cutoff, int(batch_size)),
                )
