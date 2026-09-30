"""Regression tests for the "stale chunk" bug: re-ingesting used to leave
orphaned chunks behind forever when a file/page/repo was deleted, renamed, or
shrunk, because chunk IDs are content-addressed per (source, path/url, index)
and nothing ever purged IDs that no longer exist on the new pass.
"""
from ingest import github_ingest, website_ingest


def test_purge_stale_repos_removes_repo_no_longer_present(monkeypatch, tmp_path):
    monkeypatch.setattr(
        github_ingest.vectorstore,
        "list_metadatas",
        lambda where: [{"repo": "me/deleted-repo"}, {"repo": "me/deleted-repo"}, {"repo": "me/kept-repo"}],
    )
    deleted = []
    monkeypatch.setattr(github_ingest.vectorstore, "delete_where", lambda where: deleted.append(where))

    github_ingest._purge_stale_repos({"me/kept-repo"}, tmp_path)

    assert deleted == [{"source": "github", "repo": "me/deleted-repo"}]


def test_purge_stale_repos_removes_orphaned_local_clone(monkeypatch, tmp_path):
    (tmp_path / "kept-repo").mkdir()
    (tmp_path / "deleted-repo").mkdir()
    monkeypatch.setattr(github_ingest.vectorstore, "list_metadatas", lambda where: [])
    monkeypatch.setattr(github_ingest.vectorstore, "delete_where", lambda where: None)

    github_ingest._purge_stale_repos({"me/kept-repo"}, tmp_path)

    assert (tmp_path / "kept-repo").exists()
    assert not (tmp_path / "deleted-repo").exists()


def test_purge_stale_pages_removes_url_no_longer_crawled(monkeypatch):
    monkeypatch.setattr(
        website_ingest.vectorstore,
        "list_metadatas",
        lambda where: [{"url": "https://x/gone"}, {"url": "https://x/kept"}],
    )
    deleted = []
    monkeypatch.setattr(website_ingest.vectorstore, "delete_where", lambda where: deleted.append(where))

    website_ingest._purge_stale_pages({"https://x/kept"})

    assert deleted == [{"source": "website", "url": "https://x/gone"}]
