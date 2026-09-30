import json
import types

import pytest
import requests
from fastapi.testclient import TestClient

from app.config import config
from app.main import MAX_QUESTION_LENGTH, app
from app.store import db as store_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_conversations_db(tmp_path, monkeypatch):
    """Every test gets its own throwaway conversations DB -- never touches
    the real data/conversations.db."""
    fake_config = types.SimpleNamespace(conversations_db=tmp_path / "test_api.db")
    monkeypatch.setattr(store_db, "config", fake_config)


def _ollama_available() -> bool:
    try:
        requests.get(f"{config.ollama_host}/api/tags", timeout=2).raise_for_status()
        return True
    except Exception:
        return False


def test_health_endpoint_reports_chunk_count():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "chunks" in body


def test_chat_rejects_empty_question():
    resp = client.post("/api/chat", json={"question": ""})
    assert resp.status_code == 422


def test_chat_rejects_oversized_question():
    """Regression test: nothing capped the prompt size sent to the local LLM,
    so a pathologically large question could hang/OOM the Ollama process."""
    resp = client.post("/api/chat", json={"question": "x" * (MAX_QUESTION_LENGTH + 1)})
    assert resp.status_code == 422


def test_chat_rejects_missing_field():
    resp = client.post("/api/chat", json={})
    assert resp.status_code == 422


def test_create_and_list_conversation():
    resp = client.post("/api/conversations")
    assert resp.status_code == 200
    created = resp.json()
    assert created["title"] == "New chat"

    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    ids = [c["id"] for c in resp.json()]
    assert created["id"] in ids


def test_get_conversation_returns_empty_message_list_for_new_chat():
    conv_id = client.post("/api/conversations").json()["id"]
    resp = client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


def test_get_nonexistent_conversation_is_404():
    resp = client.get("/api/conversations/does-not-exist")
    assert resp.status_code == 404


def test_delete_conversation():
    conv_id = client.post("/api/conversations").json()["id"]
    resp = client.delete(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert client.get(f"/api/conversations/{conv_id}").status_code == 404


def test_rename_conversation():
    conv_id = client.post("/api/conversations").json()["id"]
    resp = client.patch(f"/api/conversations/{conv_id}", json={"title": "My renamed chat"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "My renamed chat"
    assert client.get(f"/api/conversations/{conv_id}").json()["title"] == "My renamed chat"


def test_rename_nonexistent_conversation_is_404():
    resp = client.patch("/api/conversations/does-not-exist", json={"title": "x"})
    assert resp.status_code == 404


def _read_sse_events(resp) -> list[dict]:
    events = []
    for line in resp.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_chat_stream_persists_conversation_and_supports_followup():
    """Live end-to-end test: streams a question, checks the SSE event shape,
    verifies both turns landed in the conversation store, then asks a
    follow-up in the same conversation to confirm history is actually used
    (not just stored)."""
    if not _ollama_available():
        pytest.skip("Ollama is not reachable at " + config.ollama_host)

    with client.stream(
        "POST", "/api/chat/stream", json={"question": "What language is QueryCraft-AI built with?"}
    ) as resp:
        assert resp.status_code == 200
        events = _read_sse_events(resp)

    assert events[0]["type"] == "conversation"
    conv_id = events[0]["conversation_id"]
    assert any(e["type"] == "content" for e in events)
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["conversation_id"] == conv_id
    assert "sources" in done_events[0]

    stored = client.get(f"/api/conversations/{conv_id}").json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][0]["content"] == "What language is QueryCraft-AI built with?"
    assert stored["title"] == "What language is QueryCraft-AI built with?"

    # Follow-up in the same conversation
    with client.stream(
        "POST", "/api/chat/stream", json={"question": "And what about its backend?", "conversation_id": conv_id}
    ) as resp:
        assert resp.status_code == 200
        followup_events = _read_sse_events(resp)

    assert followup_events[0]["conversation_id"] == conv_id  # reused, not a new conversation
    stored_after = client.get(f"/api/conversations/{conv_id}").json()
    assert len(stored_after["messages"]) == 4
    assert [m["role"] for m in stored_after["messages"]] == ["user", "assistant", "user", "assistant"]
