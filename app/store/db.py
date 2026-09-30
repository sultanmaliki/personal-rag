"""SQLite connection + schema for conversation history.

A fresh, short-lived connection per call (rather than one shared connection)
sidesteps sqlite3's thread-affinity rules entirely -- simplest correct
approach for a local, low-concurrency tool, and cheap enough that pooling
isn't worth the complexity here.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from app.config import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    thinking TEXT,
    sources TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
"""


def _connect() -> sqlite3.Connection:
    config.conversations_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.conversations_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Idempotent (IF NOT EXISTS) and cheap enough to run on every connect --
    # removes any dependency on an explicit init step running first/at the
    # right time (e.g. FastAPI's lifespan may not fire under every test
    # client configuration).
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Kept as an explicit, readable call site (e.g. app startup) even
    though _connect() already ensures the schema exists on every call."""
    with connection():
        pass
