#!/usr/bin/env python
"""CLI: ingest documents dropped into info/ (PDF, Word, text, Markdown).

Usage:
    python scripts/ingest_documents.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.document_ingest import ingest  # noqa: E402

if __name__ == "__main__":
    ingest()
