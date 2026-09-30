"""Local embedding model, loaded once and reused for both ingestion and queries."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.config import config


def _model_is_cached(model_name: str) -> bool:
    cache_root = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    return (cache_root / f"models--{model_name.replace('/', '--')}").exists()


if _model_is_cached(config.embedding_model):
    # Already downloaded: skip the "is there a newer version?" network check
    # sentence-transformers/huggingface_hub otherwise does on every process
    # start, which can hang for minutes on a slow/blocked connection.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

from sentence_transformers import SentenceTransformer  # noqa: E402


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(config.embedding_model)


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
