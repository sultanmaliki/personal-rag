"""CRUD for persisted chat conversations (SQLite-backed)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.store.db import connection

MAX_AUTO_TITLE_LENGTH = 60


@dataclass
class ConversationSummary:
    id: str
    title: str
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: int
    role: str
    content: str
    thinking: str | None
    sources: list[dict] | None
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_title(first_message: str) -> str:
    title = " ".join(first_message.split())  # collapse whitespace/newlines
    if len(title) > MAX_AUTO_TITLE_LENGTH:
        title = title[: MAX_AUTO_TITLE_LENGTH - 1].rstrip() + "…"
    return title or "New chat"


def create_conversation(first_message: str | None = None) -> str:
    conv_id = uuid.uuid4().hex
    now = _now()
    title = _auto_title(first_message) if first_message else "New chat"
    with connection() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now),
        )
    return conv_id


def conversation_exists(conversation_id: str) -> bool:
    with connection() as conn:
        row = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return row is not None


def list_conversations() -> list[ConversationSummary]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    return [ConversationSummary(**dict(r)) for r in rows]


def get_messages(conversation_id: str) -> list[Message]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, thinking, sources, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    return [
        Message(
            id=r["id"],
            role=r["role"],
            content=r["content"],
            thinking=r["thinking"],
            sources=json.loads(r["sources"]) if r["sources"] else None,
            created_at=r["created_at"],
        )
        for r in rows
    ]


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    thinking: str | None = None,
    sources: list[dict] | None = None,
) -> None:
    now = _now()
    with connection() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, thinking, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, role, content, thinking, json.dumps(sources) if sources else None, now),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))


def maybe_set_title_from_first_message(conversation_id: str, message: str) -> None:
    """Conversations created without a first message (a bare 'New chat'
    click) get titled from whatever the user actually asks first."""
    with connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?", (conversation_id,)).fetchone()
        if row["n"] <= 1:  # this is the first message just inserted
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (_auto_title(message), conversation_id),
            )


def delete_conversation(conversation_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def rename_conversation(conversation_id: str, title: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title.strip()[:MAX_AUTO_TITLE_LENGTH] or "Untitled", conversation_id),
        )
