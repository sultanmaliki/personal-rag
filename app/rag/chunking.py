"""Simple character-based text chunking with overlap.

Kept deliberately dependency-free (no tokenizer/langchain) since chunk
boundaries only need to be "roughly token-sized", not exact.
"""
from __future__ import annotations


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if overlap < 0:
        raise ValueError(f"overlap must not be negative, got {overlap}")
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be smaller than chunk_size ({chunk_size})")

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    step = chunk_size - overlap

    while start < n:
        end = min(start + chunk_size, n)
        # Prefer to break at a paragraph/line boundary near the end of the window.
        if end < n:
            break_point = text.rfind("\n", start, end)
            if break_point != -1 and break_point > start + chunk_size // 2:
                end = break_point
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start += step

    return chunks
