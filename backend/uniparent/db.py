"""SQLite storage. Timestamps are UTC epoch seconds (int)."""
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'parent')),
    created       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created    INTEGER NOT NULL,
    expires    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    manual_off     INTEGER NOT NULL DEFAULT 0,
    pause_until    INTEGER,          -- off until this time
    override_until INTEGER,          -- on until this time, even inside a schedule window
    bonus_until    INTEGER           -- extra screen time: on until this time, beats every off; then locks again
);
CREATE TABLE IF NOT EXISTS devices (
    mac            TEXT PRIMARY KEY,  -- lower-case aa:bb:cc:dd:ee:ff
    label          TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'other',
    group_id       INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    manual_off     INTEGER NOT NULL DEFAULT 0,
    pause_until    INTEGER,
    override_until INTEGER,           -- on until this time even while its group is off
    applied_off    INTEGER,           -- last block state UniParent pushed (NULL = never); see Service.reconcile
    bonus_until    INTEGER,           -- extra screen time for just this device
    notes          TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS schedules (
    id       INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    days     TEXT NOT NULL,           -- weekday digits the window STARTS on, Mon=0 .. Sun=6, e.g. "0123" or "6"
    start    TEXT NOT NULL,           -- "HH:MM" local time
    end      TEXT NOT NULL,           -- "HH:MM"; earlier than start = ends next day
    enabled  INTEGER NOT NULL DEFAULT 1,
    label    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS log (
    id      INTEGER PRIMARY KEY,
    ts      INTEGER NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor   TEXT NOT NULL,            -- display name at the time, or 'Schedule' / 'System'
    action  TEXT NOT NULL,
    target  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS traffic (
    mac   TEXT NOT NULL,
    ts    INTEGER NOT NULL,
    bytes INTEGER NOT NULL,          -- tx+rx moved since the previous poll
    PRIMARY KEY (mac, ts)
);
CREATE TABLE IF NOT EXISTS counters (   -- last cumulative byte counter seen per client
    mac   TEXT PRIMARY KEY,
    total INTEGER NOT NULL,
    ts    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS traffic_ts ON traffic(ts);
"""

# Columns added after the first release: (table, column, type). CREATE TABLE above already has them;
# this only upgrades older databases in place.
MIGRATIONS = [
    ("devices", "applied_off", "INTEGER"),
    ("groups", "bonus_until", "INTEGER"),
    ("devices", "bonus_until", "INTEGER"),
]


class DB:
    """One shared connection guarded by a lock; the app's queries are tiny."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            for table, col, typ in MIGRATIONS:
                have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args=()) -> int:
        """Execute a write; returns lastrowid."""
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def log(self, actor: str, action: str, target: str = "", user_id: int | None = None):
        self.x("INSERT INTO log (ts, user_id, actor, action, target) VALUES (?,?,?,?,?)",
               (int(time.time()), user_id, actor, action, target))
