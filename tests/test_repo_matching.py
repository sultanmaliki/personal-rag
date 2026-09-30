"""Regression tests for scoping retrieval to a specifically-named repo.

Real issue found in a live 20-question evaluation: asking about the repo
literally named "sultanmaliki" (which collides with the GitHub *username*,
appearing in every indexed chunk's metadata path) got a confused answer
describing unrelated repos, because pure similarity search had no way to
prefer the one repo actually named in the question.
"""
from unittest.mock import patch

from app.rag.pipeline import _match_repo, _normalize


def test_normalize_treats_hyphens_and_underscores_as_spaces():
    assert _normalize("Custom-Language-Translator") == "custom language translator"
    assert _normalize("hospital_management_system") == "hospital management system"


REPOS = [
    "sultanmaliki/portfolio",
    "sultanmaliki/Custom-Language-Translator",
    "sultanmaliki/QueryCraft-AI",
    "sultanmaliki/hospital-management-system",
    "sultanmaliki/sultanmaliki",
    "sultanmaliki/LinkedOut",
]


def test_match_repo_finds_exact_hyphenated_name():
    with patch("app.rag.pipeline.vectorstore.list_repo_names", return_value=REPOS):
        assert _match_repo("Does the hospital-management-system use MySQL?") == "sultanmaliki/hospital-management-system"


def test_match_repo_finds_name_written_with_spaces():
    with patch("app.rag.pipeline.vectorstore.list_repo_names", return_value=REPOS):
        assert _match_repo("What language does the Custom Language Translator support?") == "sultanmaliki/Custom-Language-Translator"


def test_match_repo_handles_username_collision():
    # The repo literally named "sultanmaliki" (same as the GitHub username)
    # must still be found precisely, not confused with every other repo
    # (which are ALSO all under owner "sultanmaliki").
    with patch("app.rag.pipeline.vectorstore.list_repo_names", return_value=REPOS):
        assert _match_repo("What is in the sultanmaliki repo?") == "sultanmaliki/sultanmaliki"


def test_match_repo_returns_none_for_unrelated_question():
    with patch("app.rag.pipeline.vectorstore.list_repo_names", return_value=REPOS):
        assert _match_repo("What was my GPA in university?") is None
