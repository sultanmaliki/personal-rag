"""Retrieval-augmented answer generation."""
from __future__ import annotations

import re
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
# TESTING.md), so no amount of top-k tuning makes it comprehensive. This
# covers both "list everything" questions and "filter/count/compare across
# everything" questions (e.g. "which of my projects use X", "how many
# projects") -- both need to see every source, not just the nearest few
# chunks by raw similarity, confirmed by a live 20-question evaluation where
# every one of these phrasings gave an incomplete or wrong answer without
# this routing (see TESTING.md).
_OVERVIEW_MARKERS = (
    "what do you know", "what all do you know", "what projects", "which projects",
    "which of my projects", "which of your projects", "list your projects",
    "list my projects", "list all", "all your projects", "all my projects",
    "overview of your knowledge", "everything you know", "what have you",
    "what's in your knowledge", "what is in your knowledge", "summarize your knowledge",
    "summarize my work", "describe my work", "tell me about your projects",
    "tell me about your knowledge", "what all projects", "what do you have",
    "what all do you have", "how many projects", "how many repos",
    "how many repositories", "languages do i use", "languages have i used",
    "technologies do i use", "tech stack do i use", "across my projects",
    "across all my projects", "across your knowledge", "across all your projects",
)


def _is_overview_question(question: str) -> bool:
    q = question.lower()
    return any(marker in q for marker in _OVERVIEW_MARKERS)


def _normalize(s: str) -> str:
    return re.sub(r"[-_]+", " ", s.lower()).strip()


def _match_repo(question: str) -> str | None:
    """If the question names a specific ingested repo (by its exact GitHub
    name, hyphens/underscores treated as spaces), return its full
    'owner/repo' so retrieval can be scoped to just that repo -- fixes a real
    issue found live: a question about one repo pulling in noisy chunks from
    unrelated repos (e.g. portfolio's catalog data) ranking nearby in
    embedding space, or -- worse -- a repo whose name collides with the
    GitHub username itself ("sultanmaliki") getting near-zero precision from
    pure similarity search."""
    q_norm = _normalize(question)
    best: str | None = None
    for full_name in vectorstore.list_repo_names():
        short_norm = _normalize(full_name.split("/", 1)[-1])
        if short_norm and short_norm in q_norm:
            if best is None or len(short_norm) > len(_normalize(best.split("/", 1)[-1])):
                best = full_name
    return best


def answer_question(question: str) -> Answer:
    overview = _is_overview_question(question)
    if overview:
        retrieved = vectorstore.list_overview_chunks()
    else:
        query_vec = embeddings.embed_one(question)
        matched_repo = _match_repo(question)
        # "repo" is only ever set on github-sourced chunks, so this alone is
        # an unambiguous single-key filter (Chroma's `where` needs no $and).
        where = {"repo": matched_repo} if matched_repo else None
        retrieved = vectorstore.query(query_vec, top_k=config.top_k, where=where)
        if not retrieved and where:
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
