#!/usr/bin/env python
"""CLI: ingest all of the configured GitHub user's repos.

Usage:
    python scripts/ingest_github.py [--username NAME] [--include-forks]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.github_ingest import ingest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=None, help="Override GITHUB_USERNAME from .env")
    parser.add_argument("--include-forks", action="store_true", default=None)
    args = parser.parse_args()
    ingest(username=args.username, include_forks=args.include_forks)


if __name__ == "__main__":
    main()
