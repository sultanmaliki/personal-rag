from app.rag.chunking import chunk_text


def test_empty_text_produces_no_chunks():
    assert chunk_text("", chunk_size=100, overlap=10) == []
    assert chunk_text("   \n  ", chunk_size=100, overlap=10) == []


def test_short_text_is_a_single_chunk():
    text = "hello world"
    assert chunk_text(text, chunk_size=100, overlap=10) == [text]


def test_long_text_is_split_with_overlap():
    text = "\n".join(f"line {i}" for i in range(200))  # well over chunk_size
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    # every chunk must actually respect the size budget
    assert all(len(c) <= 100 for c in chunks)
    # reassembled content should cover the original lines (allow for overlap duplication)
    assert "line 0" in chunks[0]
    assert "line 199" in chunks[-1]


def test_huge_single_line_still_terminates():
    # A pathological "no whitespace to break on" document (e.g. minified/obfuscated
    # content that slipped past the binary filter) must not spin or infinite-loop.
    text = "x" * 50_000
    chunks = chunk_text(text, chunk_size=1000, overlap=100)
    assert sum(len(c) for c in chunks) >= len(text) - 100 * len(chunks)
    assert len(chunks) > 1
