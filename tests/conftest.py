"""Shared pytest fixtures / setup.

Load the project's ``.env`` before any test runs so the DB-backed tests resolve
``DATABASE_URL`` (Neon in production) the same way the app does via ``config.py``.
Without this, a bare ``pytest`` invocation falls back to the localhost default and
the live-warehouse tests fail against a DB that isn't running locally.
"""
from pathlib import Path

from dotenv import load_dotenv

# Project root is the parent of this tests/ directory.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
