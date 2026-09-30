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


def answer_question(question: str) -> Answer:
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
    text = llm.chat(question, context_block)
    return Answer(text=text, sources=sources)
