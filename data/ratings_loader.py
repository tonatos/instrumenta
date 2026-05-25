"""
Credit rating loader.

Two-layer rating storage:
    1. Vendored seed (``data/ratings.json``) — checked into the repo, edited
       by humans. Maps brand-name substrings to coarse ratings (e.g. ``ОФЗ``
       → ``ruAAA``). Stays read-only at runtime (mounted RO in Docker).
    2. Auto-scraped cache (``$CACHE_DIR/ratings_auto.json``) — overwritten by
       ``data.ratings_scraper.fetch_smartlab_bond_ratings``. Contains precise
       per-ISIN ratings for the most liquid bonds.

Match priority when applying ratings to a ``BondRecord``:
    1. Auto-scraped ISIN → rating (precise, per issue)
    2. Vendored ISIN → rating (manual overrides for cases the auto source
       does not cover)
    3. Vendored name-substring → rating (brand-level fallback for ОФЗ and
       smaller / less-liquid issuers)

Ratings use the Эксперт РА / АКРА national scale (``ruAAA``, ``ruAA+`` …).
The smart-lab source omits the ``ru`` prefix; ``core.bond_model.RATING_ORDER``
accepts both forms so no normalisation is required here.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.bond_model import BondRecord

logger = logging.getLogger(__name__)

# Number of most common uncovered SHORTNAME roots to surface in the log. Helps
# the operator decide which issuers to add to ``name_ratings`` next.
_UNCOVERED_LOG_TOP_N: int = 15

# A "root" of a MOEX SHORTNAME = the leading letters before the first digit or
# space, e.g. ``Ростел2P6R`` → ``Ростел``, ``МТС 1P-21`` → ``МТС``. Used purely
# for logging, not for matching.
_SHORTNAME_ROOT_RE: re.Pattern[str] = re.compile(r"^[^\s\d]+")


def _shortname_root(name: str) -> str:
    """Extract a short identifying prefix from a MOEX SHORTNAME for grouping."""
    if not name:
        return ""
    match = _SHORTNAME_ROOT_RE.match(name)
    return (match.group(0) if match else name).strip()


# ── Paths ─────────────────────────────────────────────────────────────────────

_VENDORED_RATINGS_PATH: Path = Path(__file__).parent / "ratings.json"

# Default cache dir is ``<repo_root>/cache`` so the path works identically
# inside Docker (``WORKDIR=/app`` ⇒ ``/app/cache``) and on a developer machine
# without requiring ``CACHE_DIR`` to be set explicitly.
_DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "cache"
_CACHE_DIR: Path = Path(os.getenv("CACHE_DIR") or _DEFAULT_CACHE_DIR)
AUTO_RATINGS_PATH: Path = _CACHE_DIR / "ratings_auto.json"


# ── Vendored seed loader (unchanged public API) ───────────────────────────────


def load_ratings() -> dict:
    """Load the vendored ratings JSON; return empty dict on any error."""
    if not _VENDORED_RATINGS_PATH.exists():
        logger.warning("ratings.json not found at %s", _VENDORED_RATINGS_PATH)
        return {}
    try:
        with _VENDORED_RATINGS_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        logger.info(
            "Loaded vendored ratings: %d ISIN entries, %d name patterns",
            len(data.get("isin_ratings", {})),
            len(data.get("name_ratings", {})),
        )
        return data
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load %s", _VENDORED_RATINGS_PATH)
        return {}


# ── Auto-scraped cache layer ──────────────────────────────────────────────────


def load_auto_ratings() -> dict[str, Any] | None:
    """
    Return the auto-scraped ratings cache (full envelope) or ``None`` if the
    cache file is absent / malformed.

    Envelope keys: ``isin_ratings`` (required), ``_source``, ``_updated_at``,
    ``_count``.
    """
    if not AUTO_RATINGS_PATH.exists():
        return None
    try:
        with AUTO_RATINGS_PATH.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load %s", AUTO_RATINGS_PATH)
        return None
    if not isinstance(data.get("isin_ratings"), dict):
        logger.warning("Auto-ratings cache has unexpected shape at %s", AUTO_RATINGS_PATH)
        return None
    return data


def save_auto_ratings(
    isin_to_rating: dict[str, str],
    *,
    source: str,
) -> Path:
    """
    Atomically persist scraped ratings to ``AUTO_RATINGS_PATH``.

    Args:
        isin_to_rating: ISIN → rating mapping. Will be sorted for stable diffs.
        source: Human-readable source identifier (e.g. URL) for the envelope.

    Returns:
        The path the cache was written to.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "_source": source,
        "_updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "_count": len(isin_to_rating),
        "isin_ratings": dict(sorted(isin_to_rating.items())),
    }
    tmp_path = AUTO_RATINGS_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp_path.replace(AUTO_RATINGS_PATH)
    logger.info(
        "Auto-ratings cache saved: %d entries → %s",
        len(isin_to_rating),
        AUTO_RATINGS_PATH,
    )
    return AUTO_RATINGS_PATH


# ── Application ───────────────────────────────────────────────────────────────


def apply_ratings(
    bonds: list[BondRecord],
    ratings: dict,
    auto_ratings: dict[str, Any] | None = None,
) -> list[BondRecord]:
    """
    Apply credit ratings to bonds in-place; return the same list.

    Resolution order (first non-empty hit wins):
        1. Auto-scraped ISIN match (precise, per issue)
        2. Vendored ISIN match (manual ISIN overrides)
        3. Vendored name-substring match (brand-level fallback)

    Args:
        bonds: List of bonds to enrich.
        ratings: Output of :func:`load_ratings`.
        auto_ratings: Output of :func:`load_auto_ratings`, or ``None`` to skip
            the auto layer entirely.
    """
    auto_isin: dict[str, str] = {}
    if auto_ratings is not None:
        auto_isin = auto_ratings.get("isin_ratings", {}) or {}

    vendored_isin: dict[str, str] = ratings.get("isin_ratings", {}) or {}
    vendored_names: dict[str, str] = {
        k.lower(): v for k, v in (ratings.get("name_ratings", {}) or {}).items()
    }

    matched_auto = 0
    matched_vendored_isin = 0
    matched_vendored_name = 0
    uncovered: list[BondRecord] = []

    for bond in bonds:
        rating = auto_isin.get(bond.isin)
        if rating:
            bond.credit_rating = rating
            matched_auto += 1
            continue

        rating = vendored_isin.get(bond.isin)
        if rating:
            bond.credit_rating = rating
            matched_vendored_isin += 1
            continue

        name_lower = bond.name.lower()
        matched = False
        for pattern, fallback in vendored_names.items():
            if pattern in name_lower:
                bond.credit_rating = fallback
                matched_vendored_name += 1
                matched = True
                break
        if not matched:
            uncovered.append(bond)

    total_matched = matched_auto + matched_vendored_isin + matched_vendored_name
    logger.info(
        "Ratings applied: auto=%d, vendored_isin=%d, vendored_name=%d, total=%d/%d",
        matched_auto,
        matched_vendored_isin,
        matched_vendored_name,
        total_matched,
        len(bonds),
    )

    if uncovered:
        root_counts = Counter(_shortname_root(bond.name) for bond in uncovered)
        top = root_counts.most_common(_UNCOVERED_LOG_TOP_N)
        top_str = ", ".join(f"{root}×{count}" for root, count in top)
        logger.info(
            "Ratings uncovered: %d/%d bonds. Top SHORTNAME roots: %s",
            len(uncovered),
            len(bonds),
            top_str,
        )

    return bonds
