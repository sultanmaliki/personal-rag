"""Retrieval-augmented answer generation."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import config
from app.rag import embeddings, llm, vectorstore


@dataclass
class Source:
    label: str
    ref: str  # file path or URL


@dataclass
class Answer:
    text: str
    sources: list[Source]


def _describe_source(metadata: dict) -> Source:
    if metadata.get("source") == "github":
        return Source(label=f"{metadata['repo']}:{metadata['path']}", ref=metadata.get("url", ""))
    return Source(label=metadata.get("title") or metadata.get("url", "web page"), ref=metadata.get("url", ""))


# Broad "survey the whole corpus" questions need different retrieval than
# specific factual ones: pure similarity search can leave most of the corpus
# nowhere near the query in embedding space (confirmed directly -- see
# TESTING.md), so no amount of top-k tuning makes it comprehensive. These
# route to vectorstore.list_overview_chunks() instead, which guarantees one
# chunk per source by construction rather than by semantic luck.
_OVERVIEW_MARKERS = (
    "what do you know", "what all do you know", "what projects", "which projects",
    "list your projects", "list my projects", "list all", "all your projects",
    "all my projects", "overview of your knowledge", "everything you know",
    "what have you", "what's in your knowledge", "what is in your knowledge",
    "summarize your knowledge", "tell me about your projects", "what all projects",
    "what do you have", "what all do you have",
)


def _is_overview_question(question: str) -> bool:
    q = question.lower()
    return any(marker in q for marker in _OVERVIEW_MARKERS)


def answer_question(question: str) -> Answer:
    overview = _is_overview_question(question)
    if overview:
        retrieved = vectorstore.list_overview_chunks()
    else:
        query_vec = embeddings.embed_one(question)
        retrieved = vectorstore.query(query_vec, top_k=config.top_k)

    if not retrieved:
        return Answer(
            text="My knowledge base is empty. Run the ingestion scripts first "
            "(scripts/ingest_github.py and scripts/ingest_website.py).",
            sources=[],
        )

    context_lines = []
    sources: list[Source] = []
    for i, chunk in enumerate(retrieved, start=1):
        source = _describe_source(chunk.metadata)
        sources.append(source)
        context_lines.append(f"[{i}] ({source.label})\n{chunk.text}")

    context_block = "\n\n".join(context_lines)
    text = llm.chat(question, context_block, comprehensive=overview)
    return Answer(text=text, sources=sources)
