"""Ingest all of the user's GitHub repos (via the `gh` CLI) into the vector store.

Uses `gh` for both listing and cloning so no raw GitHub token ever needs to be
handled here -- it relies entirely on the credentials `gh auth login` already
set up.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from app.config import config
from app.rag import vectorstore
from ingest.common import chunks_from_document, embed_and_store

EXCLUDED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", "target", "vendor", ".idea", ".vscode", "coverage", ".cache",
    ".pytest_cache", "site-packages", ".mypy_cache", "out",
}

EXCLUDED_SUFFIXES = {
    ".lock", ".min.js", ".min.css", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".webp", ".avif", ".bmp", ".tiff", ".heic", ".pdf", ".zip",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".mov", ".webm",
    ".mp3", ".wav", ".flac", ".ogg", ".bin", ".exe", ".dll", ".so",
    ".class", ".jar", ".wasm", ".map",
}

EXCLUDED_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}

MAX_FILE_SIZE = 300_000


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def list_repos(username: str) -> list[dict]:
    result = _run(
        [
            "gh", "repo", "list", username,
            "--limit", "1000",
            "--json", "name,nameWithOwner,isPrivate,isFork,defaultBranchRef,updatedAt",
        ]
    )
    return json.loads(result.stdout)


def _force_remove(func, path, _exc) -> None:
    # git marks pack files read-only on Windows; clear that before retrying.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clone_repo(name_with_owner: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, onexc=_force_remove)
    _run(["gh", "repo", "clone", name_with_owner, str(dest), "--", "--depth", "1"])


def _is_text_file(path: Path) -> bool:
    if path.name in EXCLUDED_NAMES:
        return False
    if any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    try:
        if path.stat().st_size > MAX_FILE_SIZE or path.stat().st_size == 0:
            return False
    except OSError:
        return False
    return True


def _looks_binary(raw: bytes) -> bool:
    # Same heuristic git uses: a NUL byte in the first few KB means "binary".
    return b"\x00" in raw[:8000]


def walk_files(repo_dir: Path):
    for path in repo_dir.rglob("*"):
        if path.is_dir():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if not _is_text_file(path):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if _looks_binary(raw):
            continue
        text = raw.decode("utf-8", errors="ignore")
        if text.strip():
            yield path.relative_to(repo_dir).as_posix(), text


def _purge_stale_repos(kept_names: set[str], repos_dir: Path) -> None:
    """Remove vector-store chunks and local clones for repos no longer listed
    (deleted, renamed, or newly a fork that's now excluded)."""
    stored_repos = {
        m["repo"] for m in vectorstore.list_metadatas({"source": "github"}) if m.get("repo")
    }
    for stale in stored_repos - kept_names:
        print(f"purging stale repo from index: {stale}")
        vectorstore.delete_where({"source": "github", "repo": stale})

    if not repos_dir.exists():
        return
    kept_dir_names = {name.split("/", 1)[-1] for name in kept_names}
    for entry in repos_dir.iterdir():
        if entry.is_dir() and entry.name not in kept_dir_names:
            print(f"removing orphaned local clone: {entry.name}")
            shutil.rmtree(entry, onexc=_force_remove)


def ingest(username: str | None = None, include_forks: bool | None = None) -> None:
    username = username or config.github_username
    include_forks = config.include_forks if include_forks is None else include_forks

    repos = list_repos(username)
    print(f"Found {len(repos)} repos for {username}.")

    kept = [r for r in repos if include_forks or not r["isFork"]]
    for repo in repos:
        if repo["isFork"] and not include_forks:
            print(f"skip (fork): {repo['nameWithOwner']}")

    _purge_stale_repos({r["nameWithOwner"] for r in kept}, config.repos_dir)

    for repo in kept:
        name_with_owner = repo["nameWithOwner"]
        # Defence in depth: GitHub repo names can't actually contain path
        # separators, but never let an API response dictate a filesystem path.
        if "/" in repo["name"] or ".." in repo["name"]:
            print(f"  skip (unsafe repo name): {repo['name']!r}")
            continue

        branch = (repo.get("defaultBranchRef") or {}).get("name") or "main"
        dest = config.repos_dir / repo["name"]

        print(f"cloning {name_with_owner} ...")
        try:
            clone_repo(name_with_owner, dest)
        except subprocess.CalledProcessError as exc:
            print(f"  failed to clone {name_with_owner}: {exc.stderr.strip()}")
            continue

        repo_chunks = []
        for rel_path, text in walk_files(dest):
            metadata = {
                "source": "github",
                "repo": name_with_owner,
                "path": rel_path,
                "url": f"https://github.com/{name_with_owner}/blob/{branch}/{rel_path}",
            }
            repo_chunks.extend(chunks_from_document(f"{name_with_owner}:{rel_path}", text, metadata))

        # Clear this repo's previous chunks first so deleted/renamed/shrunk
        # files don't leave stale chunks behind (re-clone is a full refresh).
        vectorstore.delete_where({"source": "github", "repo": name_with_owner})
        print(f"  {len(repo_chunks)} chunks from {name_with_owner}")
        embed_and_store(repo_chunks, label=f"chunks ({name_with_owner})")


if __name__ == "__main__":
    ingest()
