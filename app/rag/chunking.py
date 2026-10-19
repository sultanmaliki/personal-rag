"""Simple character-based text chunking with overlap.

Kept deliberately dependency-free (no tokenizer/langchain) since chunk
boundaries only need to be "roughly token-sized", not exact.
"""
from __future__ import annotations


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    step = max(chunk_size - overlap, 1)

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
