"""Shared helpers for ingestion scripts."""
from __future__ import annotations

import hashlib

from app.config import config
from app.rag import embeddings, vectorstore
from app.rag.chunking import chunk_text
from app.rag.vectorstore import Chunk

BATCH_SIZE = 64


def make_id(*parts: str) -> str:
    digest = hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def chunks_from_document(doc_id_prefix: str, text: str, metadata: dict) -> list[Chunk]:
    pieces = chunk_text(text, config.chunk_size, config.chunk_overlap)
    return [
        Chunk(id=make_id(doc_id_prefix, str(i)), text=piece, metadata={**metadata, "chunk_index": i})
        for i, piece in enumerate(pieces)
    ]


def embed_and_store(all_chunks: list[Chunk], label: str = "chunks") -> None:
    total = len(all_chunks)
    if total == 0:
        print(f"No {label} to store.")
        return
    for start in range(0, total, BATCH_SIZE):
        batch = all_chunks[start : start + BATCH_SIZE]
        vectors = embeddings.embed([c.text for c in batch])
        vectorstore.upsert(batch, vectors)
        done = min(start + BATCH_SIZE, total)
        print(f"  embedded {done}/{total} {label}")
