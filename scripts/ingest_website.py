#!/usr/bin/env python
"""CLI: crawl and ingest the configured website (and discovered subdomains).

Usage:
    python scripts/ingest_website.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.website_ingest import ingest  # noqa: E402

if __name__ == "__main__":
    ingest()
