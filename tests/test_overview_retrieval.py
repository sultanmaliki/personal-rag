"""Regression tests for broad "what do you know" style questions.

Real bug reported by the user (with a screenshot): pure top-k similarity
search answered "what all do you know" using only the single repo whose
chunks happened to be nearest that phrase in embedding space, even after
the source-diversity cap (test_retrieval_diversity.py) -- because most of
the corpus simply isn't semantically close to that phrasing at all. Fixed
by routing broad questions to a dedicated overview-retrieval path that
guarantees full-corpus coverage by construction instead of by similarity.
"""
from app.rag.pipeline import _is_overview_question


def test_recognizes_broad_overview_questions():
    for q in [
        "what do you know",
        "What all do you know?",
        "what projects have you indexed",
        "List all your projects",
        "Tell me about your projects",
        "what have you got",
    ]:
        assert _is_overview_question(q), f"expected {q!r} to be recognized as an overview question"


def test_does_not_misclassify_specific_questions():
    for q in [
        "What language is QueryCraft-AI built with?",
        "Does the hospital-management-system use MySQL?",
        "What is my GPA?",
        "How does the crawler handle redirects?",
    ]:
        assert not _is_overview_question(q), f"expected {q!r} to NOT be treated as an overview question"
