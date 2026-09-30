from fastapi.testclient import TestClient

from app.main import MAX_QUESTION_LENGTH, app

client = TestClient(app)


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
