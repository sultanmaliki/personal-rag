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


def query(query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
    collection = get_collection()
    if collection.count() == 0:
        return []
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
    )
    out: list[RetrievedChunk] = []
    docs = result.get("documents") or [[]]
    metas = result.get("metadatas") or [[]]
    dists = result.get("distances") or [[]]
    for text, meta, dist in zip(docs[0], metas[0], dists[0]):
        out.append(RetrievedChunk(text=text, metadata=meta, distance=dist))
    return out


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
