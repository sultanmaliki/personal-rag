"""Thin wrapper around a local, persistent Chroma collection."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import chromadb

from app.config import config


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]


@dataclass
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    distance: float


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(config.chroma_dir))


def get_collection():
    return get_client().get_or_create_collection(
        name=config.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert(chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    if not chunks:
        return
    collection = get_collection()
    collection.upsert(
        ids=[c.id for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[c.metadata for c in chunks],
    )


def _source_key(metadata: dict[str, Any]) -> str:
    return metadata.get("repo") or metadata.get("url") or ""


def _diversify(candidates: list[RetrievedChunk], top_k: int, max_per_source: int) -> list[RetrievedChunk]:
    """Cap how many chunks from the same repo/page can occupy the final
    top-k, so one large homogeneous file (e.g. a data file whose chunks are
    all semantically similar to a broad question) can't monopolize every
    citation. Candidates are assumed pre-sorted by relevance (closest
    distance first); ties/overflow fall back to next-best regardless of
    source once genuinely diverse options run out, so top_k is always filled
    when enough candidates exist."""
    selected: list[RetrievedChunk] = []
    overflow: list[RetrievedChunk] = []
    counts: dict[str, int] = {}

    for chunk in candidates:
        key = _source_key(chunk.metadata)
        if counts.get(key, 0) < max_per_source:
            selected.append(chunk)
            counts[key] = counts.get(key, 0) + 1
        else:
            overflow.append(chunk)
        if len(selected) >= top_k:
            return selected[:top_k]

    selected.extend(overflow[: top_k - len(selected)])
    return selected[:top_k]


def query(
    query_embedding: list[float],
    top_k: int,
    max_per_source: int = 3,
    pool_multiplier: int = 4,
    where: dict[str, Any] | None = None,
) -> list[RetrievedChunk]:
    collection = get_collection()
    if collection.count() == 0:
        return []
    pool_size = min(top_k * pool_multiplier, collection.count())
    kwargs: dict[str, Any] = {"query_embeddings": [query_embedding], "n_results": pool_size}
    if where:
        kwargs["where"] = where
    result = collection.query(**kwargs)
    candidates: list[RetrievedChunk] = []
    docs = result.get("documents") or [[]]
    metas = result.get("metadatas") or [[]]
    dists = result.get("distances") or [[]]
    for text, meta, dist in zip(docs[0], metas[0], dists[0]):
        candidates.append(RetrievedChunk(text=text, metadata=meta, distance=dist))
    return _diversify(candidates, top_k, max_per_source)


def list_repo_names() -> list[str]:
    """Distinct 'owner/repo' values currently indexed, for matching a
    question against a specific repo by name."""
    metas = list_metadatas({"source": "github"})
    return sorted({m["repo"] for m in metas if m.get("repo")})


def list_overview_chunks() -> list[RetrievedChunk]:
    """One representative chunk per distinct source (each GitHub repo's
    README opening chunk, falling back to that repo's first indexed chunk if
    it has no README; each website page's opening chunk).

    Pure similarity search is the wrong tool for broad "what do you know"
    style questions: a corpus can easily have most of its repos nowhere near
    that phrasing in embedding space (confirmed by direct inspection -- see
    TESTING.md), so top-k search under-samples the corpus no matter how the
    pool/cap is tuned. This instead guarantees full-corpus coverage by
    construction rather than by semantic luck.
    """
    collection = get_collection()

    readme_result = collection.get(
        where={"$and": [{"source": "github"}, {"path": "README.md"}, {"chunk_index": 0}]},
        include=["documents", "metadatas"],
    )
    chunks = [
        RetrievedChunk(text=doc, metadata=meta, distance=0.0)
        for doc, meta in zip(readme_result.get("documents") or [], readme_result.get("metadatas") or [])
    ]
    covered_repos = {c.metadata["repo"] for c in chunks}

    # Fallback for repos with no README.md: take each such repo's first
    # indexed chunk (of whichever file happens to sort first) as its stand-in.
    github_first_chunks = collection.get(
        where={"$and": [{"source": "github"}, {"chunk_index": 0}]},
        include=["documents", "metadatas"],
    )
    for doc, meta in zip(github_first_chunks.get("documents") or [], github_first_chunks.get("metadatas") or []):
        repo = meta.get("repo")
        if repo and repo not in covered_repos:
            chunks.append(RetrievedChunk(text=doc, metadata=meta, distance=0.0))
            covered_repos.add(repo)

    website_result = collection.get(
        where={"$and": [{"source": "website"}, {"chunk_index": 0}]},
        include=["documents", "metadatas"],
    )
    chunks.extend(
        RetrievedChunk(text=doc, metadata=meta, distance=0.0)
        for doc, meta in zip(website_result.get("documents") or [], website_result.get("metadatas") or [])
    )

    return chunks


def _where(metadata: dict[str, Any]) -> dict[str, Any]:
    if len(metadata) == 1:
        ((key, value),) = metadata.items()
        return {key: value}
    return {"$and": [{k: v} for k, v in metadata.items()]}


def delete_where(metadata: dict[str, Any]) -> None:
    """Delete every chunk matching an exact-match filter, e.g. {"repo": "..."}."""
    get_collection().delete(where=_where(metadata))


def list_metadatas(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch metadata for every chunk matching an exact-match filter."""
    result = get_collection().get(where=_where(metadata), include=["metadatas"])
    return result.get("metadatas") or []


def stats() -> dict[str, Any]:
    collection = get_collection()
    return {"collection": config.collection_name, "chunks": collection.count()}
