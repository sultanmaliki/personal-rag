import types

from ingest import github_ingest as gi


def test_walk_files_skips_binary_content_regardless_of_extension(tmp_path):
    """Regression test: the first ingestion run treated 300 .webp images as
    text (decoding garbage bytes with errors='ignore'), producing ~9500
    garbage chunks from one repo. Extension blocklists are inherently
    incomplete, so the real fix is sniffing content for NUL bytes."""
    binary_file = tmp_path / "photo.unknownext"
    binary_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 100)

    text_file = tmp_path / "README.md"
    text_file.write_text("# hello\nthis is real text\n", encoding="utf-8")

    found = dict(gi.walk_files(tmp_path))
    assert "README.md" in found
    assert "photo.unknownext" not in found


def test_walk_files_skips_known_binary_suffixes(tmp_path):
    (tmp_path / "image.webp").write_bytes(b"RIFF....WEBPVP8 ")
    (tmp_path / "font.woff2").write_bytes(b"wOF2")
    found = dict(gi.walk_files(tmp_path))
    assert found == {}


def test_walk_files_excludes_dependency_and_build_dirs(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("junk", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')", encoding="utf-8")

    found = dict(gi.walk_files(tmp_path))
    assert "src/app.py" in found
    assert not any("node_modules" in p for p in found)


def test_ingest_rejects_unsafe_repo_name(monkeypatch, tmp_path):
    """Defence in depth: never let a repo-list API response dictate a
    filesystem path, even though GitHub itself disallows '/' in repo names."""
    monkeypatch.setattr(gi, "list_repos", lambda username: [
        {"name": "../evil", "nameWithOwner": "me/../evil", "isFork": False, "defaultBranchRef": {"name": "main"}}
    ])
    # config is a frozen dataclass singleton -- rebind the module-level name
    # rather than mutating it, so this never touches the real data/repos dir.
    fake_config = types.SimpleNamespace(repos_dir=tmp_path, include_forks=False, github_username="me")
    monkeypatch.setattr(gi, "config", fake_config)
    monkeypatch.setattr(gi.vectorstore, "list_metadatas", lambda where: [])
    monkeypatch.setattr(gi.vectorstore, "delete_where", lambda where: None)

    clone_calls = []
    monkeypatch.setattr(gi, "clone_repo", lambda name, dest: clone_calls.append((name, dest)))

    gi.ingest(username="me")

    assert clone_calls == []  # the unsafe repo was never cloned
