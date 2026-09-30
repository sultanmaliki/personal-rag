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
) -> list[RetrievedChunk]:
    collection = get_collection()
    if collection.count() == 0:
        return []
    pool_size = min(top_k * pool_multiplier, collection.count())
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=pool_size,
    )
    candidates: list[RetrievedChunk] = []
    docs = result.get("documents") or [[]]
    metas = result.get("metadatas") or [[]]
    dists = result.get("distances") or [[]]
    for text, meta, dist in zip(docs[0], metas[0], dists[0]):
        candidates.append(RetrievedChunk(text=text, metadata=meta, distance=dist))
    return _diversify(candidates, top_k, max_per_source)


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
