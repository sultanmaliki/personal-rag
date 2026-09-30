from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.rag import pipeline, vectorstore
from app.store import conversations
from app.store.db import init_db

STATIC_DIR = Path(__file__).parent / "static"
MAX_QUESTION_LENGTH = 4000  # guards the local LLM against a pathologically huge prompt


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Personal RAG", lifespan=lifespan)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Force revalidation on every load for the static chat UI. Without this,
    browsers cache app.js/style.css on heuristic freshness (no explicit
    Cache-Control from StaticFiles), so editing the UI locally silently
    serves stale JS until a hard refresh -- confusing during development."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.add_middleware(NoCacheStaticMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class ChatStreamRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_id: str | None = None


class SourceOut(BaseModel):
    label: str
    ref: str


class ChatResponse(BaseModel):
    answer: str
    thinking: str = ""
    sources: list[SourceOut]


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    thinking: str | None
    sources: list[SourceOut] | None
    created_at: str


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, **vectorstore.stats()}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming, stateless Q&A -- used by scripts/tests. The live UI
    uses /api/chat/stream instead, which also persists conversation history."""
    result = pipeline.answer_question(req.question)
    return ChatResponse(
        answer=result.text,
        thinking=result.thinking,
        sources=[SourceOut(label=s.label, ref=s.ref) for s in result.sources],
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@app.post("/api/chat/stream")
def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
    is_new = not req.conversation_id or not conversations.conversation_exists(req.conversation_id)
    conversation_id = req.conversation_id if not is_new else conversations.create_conversation(req.question)

    prior_messages = [] if is_new else conversations.get_messages(conversation_id)
    history = [{"role": m.role, "content": m.content} for m in prior_messages]

    conversations.add_message(conversation_id, "user", req.question)
    if not is_new:
        conversations.maybe_set_title_from_first_message(conversation_id, req.question)

    def event_stream():
        yield _sse({"type": "conversation", "conversation_id": conversation_id})
        for event in pipeline.answer_question_stream(req.question, history=history):
            if event["type"] == "done":
                sources_out = [{"label": s.label, "ref": s.ref} for s in event["sources"]]
                conversations.add_message(
                    conversation_id,
                    "assistant",
                    event["answer"],
                    thinking=event.get("thinking") or None,
                    sources=sources_out,
                )
                yield _sse({"type": "done", "conversation_id": conversation_id, "sources": sources_out})
            else:
                yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations() -> list[ConversationOut]:
    return [ConversationOut(**vars(c)) for c in conversations.list_conversations()]


@app.post("/api/conversations", response_model=ConversationOut)
def create_conversation() -> ConversationOut:
    conv_id = conversations.create_conversation()
    summary = next(c for c in conversations.list_conversations() if c.id == conv_id)
    return ConversationOut(**vars(summary))


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(conversation_id: str) -> ConversationDetailOut:
    if not conversations.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    summary = next(c for c in conversations.list_conversations() if c.id == conversation_id)
    messages = conversations.get_messages(conversation_id)
    return ConversationDetailOut(
        **vars(summary),
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                thinking=m.thinking,
                sources=[SourceOut(**s) for s in m.sources] if m.sources else None,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    conversations.delete_conversation(conversation_id)
    return {"ok": True}


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(conversation_id: str, req: RenameRequest) -> ConversationOut:
    if not conversations.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversations.rename_conversation(conversation_id, req.title)
    summary = next(c for c in conversations.list_conversations() if c.id == conversation_id)
    return ConversationOut(**vars(summary))
