from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.rag import pipeline, vectorstore

STATIC_DIR = Path(__file__).parent / "static"
MAX_QUESTION_LENGTH = 4000  # guards the local LLM against a pathologically huge prompt

app = FastAPI(title="Personal RAG")


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


class SourceOut(BaseModel):
    label: str
    ref: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, **vectorstore.stats()}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    result = pipeline.answer_question(req.question)
    return ChatResponse(
        answer=result.text,
        sources=[SourceOut(label=s.label, ref=s.ref) for s in result.sources],
    )
