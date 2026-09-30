"""Regression test for a real bug seen in production: a broad question
("what all do you know") returned all 6 citations from the exact same file
(Custom-Language-Translator's data/pairs.tsv) because plain top-k cosine
search doesn't care that six near-duplicate chunks all came from one place.
"""
from app.rag.vectorstore import RetrievedChunk, _diversify


def _chunk(repo: str, i: int, distance: float) -> RetrievedChunk:
    return RetrievedChunk(text=f"{repo} chunk {i}", metadata={"source": "github", "repo": repo}, distance=distance)


def test_diversify_caps_chunks_per_source_when_alternatives_exist():
    # Exactly the observed scenario: one repo's chunks dominate by raw
    # similarity, but two other repos have relevant (slightly less similar)
    # content available too.
    candidates = (
        [_chunk("me/translator", i, distance=0.1 + i * 0.01) for i in range(6)]
        + [_chunk("me/portfolio", i, distance=0.2 + i * 0.01) for i in range(2)]
        + [_chunk("me/setbeat", i, distance=0.25 + i * 0.01) for i in range(2)]
    )

    result = _diversify(candidates, top_k=6, max_per_source=2)

    assert len(result) == 6
    repos = [c.metadata["repo"] for c in result]
    assert repos.count("me/translator") == 2  # capped, not all 6
    assert repos.count("me/portfolio") == 2
    assert repos.count("me/setbeat") == 2


def test_diversify_falls_back_to_same_source_when_no_alternatives():
    # If there genuinely isn't enough diverse content, top_k must still be
    # filled -- diversity is a preference, not a hard requirement that
    # starves the answer of context.
    candidates = [_chunk("me/only-repo", i, distance=0.1 + i * 0.01) for i in range(6)]

    result = _diversify(candidates, top_k=6, max_per_source=2)

    assert len(result) == 6
    assert all(c.metadata["repo"] == "me/only-repo" for c in result)


def test_diversify_preserves_relevance_order_within_cap():
    candidates = [_chunk("me/translator", i, distance=0.1 + i * 0.01) for i in range(6)]
    candidates += [_chunk("me/portfolio", 0, distance=0.5)]

    result = _diversify(candidates, top_k=3, max_per_source=2)

    # The two most relevant translator chunks come first, then the
    # next-best distinct source fills the remaining slot.
    assert [c.text for c in result] == [
        "me/translator chunk 0",
        "me/translator chunk 1",
        "me/portfolio chunk 0",
    ]
