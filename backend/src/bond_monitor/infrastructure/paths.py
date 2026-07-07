"""Shared filesystem paths for infrastructure layer."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]


def get_cache_dir() -> Path:
    """Return cache directory (overridable via CACHE_DIR env)."""
    return Path(os.getenv("CACHE_DIR") or (_REPO_ROOT / "cache"))


def get_ratings_json_path() -> Path:
    """Return path to vendored ratings.json."""
    return _REPO_ROOT / "data" / "ratings.json"
