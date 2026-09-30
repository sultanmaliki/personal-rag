"""Central configuration, loaded from environment variables (and .env if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    val = os.getenv(name, default)
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    # GitHub
    github_username: str = os.getenv("GITHUB_USERNAME", "sultanmaliki")
    include_forks: bool = _bool("INCLUDE_FORKS", False)

    # Website
    website_root_domain: str = os.getenv("WEBSITE_ROOT_DOMAIN", "syedmohammedsultan.online")
    website_seed_urls: list[str] = field(
        default_factory=lambda: _list("WEBSITE_SEED_URLS", "https://syedmohammedsultan.online")
    )
    website_discover_subdomains: bool = _bool("WEBSITE_DISCOVER_SUBDOMAINS", True)
    website_max_pages: int = int(os.getenv("WEBSITE_MAX_PAGES", "300"))

    # Storage
    chroma_dir: Path = PROJECT_ROOT / os.getenv("CHROMA_DIR", "./data/chroma").lstrip("./")
    repos_dir: Path = PROJECT_ROOT / os.getenv("REPOS_DIR", "./data/repos").lstrip("./")
    collection_name: str = os.getenv("COLLECTION_NAME", "personal_knowledge")
    conversations_db: Path = PROJECT_ROOT / os.getenv("CONVERSATIONS_DB", "./data/conversations.db").lstrip("./")

    # Embeddings
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    # LLM
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:14b")

    # Chunking / retrieval
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1200"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    top_k: int = int(os.getenv("TOP_K", "6"))


config = Config()
config.chroma_dir.mkdir(parents=True, exist_ok=True)
config.repos_dir.mkdir(parents=True, exist_ok=True)
