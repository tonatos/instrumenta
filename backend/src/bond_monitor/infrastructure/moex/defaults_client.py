"""
MOEX ISS default-flag enricher.

The global ``/engines/stock/markets/bonds/securities.json`` endpoint that
``data.moex_client`` uses does NOT expose the ``HASDEFAULT`` /
``HASTECHNICALDEFAULT`` flags — those live only in the per-instrument
description block at ``/iss/securities/{isin}.json``. Reference:
https://iss.moex.com/iss/reference/13

To stay under a reasonable round-trip budget we:

* Only enrich the *filtered* screener window (~50–200 bonds), not the
  full ≈3 000 universe.
* Issue per-ISIN requests concurrently via ``ThreadPoolExecutor`` —
  MOEX ISS handles a small pool well, and httpx with a default Connection
  pool keeps connection reuse cheap.
* Persist results to disk with a long TTL — default status changes very
  rarely (days/weeks), so a 24 h cache is more than fresh enough and
  removes the per-bond round-trip on every page rerun.

The disk cache is keyed by ISIN with timestamp metadata; entries older
than ``CACHE_TTL_SECONDS`` are refetched, fresher entries are reused as
is. Network errors degrade gracefully — the affected bond keeps
``has_default = False`` rather than failing the whole pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import httpx

from bond_monitor.domain.bonds.models import BondRecord

logger = logging.getLogger(__name__)

MOEX_ISS_BASE = "https://iss.moex.com/iss"

# Default flag changes rarely (issuer either is in default or isn't), so
# a long-ish TTL is fine. We still re-fetch every 24 h to pick up status
# changes (e.g. grace-period expiry promoting tech-default → default).
CACHE_TTL_SECONDS: int = 24 * 60 * 60  # 24 h

from bond_monitor.infrastructure.paths import get_cache_dir

_CACHE_DIR: Path = get_cache_dir()
_CACHE_FILE: Path = _CACHE_DIR / "moex_defaults.json"

# Keep the pool conservative — ISS rate-limits aggressive callers.
_MAX_WORKERS: int = 10
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)


@dataclass(frozen=True)
class DefaultStatus:
    has_default: bool
    has_technical_default: bool


# ─────────────────────────────────────────────────────────────────────────────
#  Disk cache
# ─────────────────────────────────────────────────────────────────────────────


def _load_cache() -> dict[str, dict]:
    """Return the on-disk cache, or an empty dict if missing/corrupt."""
    if not _CACHE_FILE.exists():
        return {}
    try:
        with _CACHE_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.warning("Defaults cache root is not a dict, ignoring")
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        logger.warning("Defaults cache read failed, will refresh", exc_info=True)
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    """Atomically write the cache to disk."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _CACHE_FILE.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_path.replace(_CACHE_FILE)
    except OSError:
        logger.warning("Defaults cache save failed", exc_info=True)


def _cache_entry_is_fresh(entry: dict, now: float) -> bool:
    ts = entry.get("ts")
    if not isinstance(ts, int | float):
        return False
    return (now - ts) < CACHE_TTL_SECONDS


# ─────────────────────────────────────────────────────────────────────────────
#  Network fetch (one ISIN)
# ─────────────────────────────────────────────────────────────────────────────


def _parse_bool(raw: object) -> bool:
    """ISS encodes booleans as the strings '0' / '1' (and sometimes ints)."""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip() == "1"
    return False


def _fetch_one(client: httpx.Client, isin: str) -> DefaultStatus | None:
    """Fetch HASDEFAULT/HASTECHNICALDEFAULT for one ISIN. Returns None on error."""
    url = f"{MOEX_ISS_BASE}/securities/{isin}.json"
    params = {
        "iss.meta": "off",
        "iss.only": "description",
        "description.columns": "name,value",
    }
    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        rows = resp.json().get("description", {}).get("data") or []
    except (httpx.HTTPError, ValueError):
        logger.debug("Defaults fetch failed for %s", isin, exc_info=True)
        return None

    by_name = {row[0]: row[1] for row in rows if isinstance(row, list) and len(row) >= 2}
    return DefaultStatus(
        has_default=_parse_bool(by_name.get("HASDEFAULT")),
        has_technical_default=_parse_bool(by_name.get("HASTECHNICALDEFAULT")),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────


def enrich_bonds_with_defaults(bonds: list[BondRecord]) -> list[BondRecord]:
    """
    Populate ``has_default`` / ``has_technical_default`` on each BondRecord.

    The function mutates and returns the same list of bonds. Unknown ISINs
    (e.g. empty string) are left with default ``False`` flags and skipped.
    Bonds whose default status is already fresh in the disk cache are not
    refetched.
    """
    if not bonds:
        return bonds

    cache = _load_cache()
    now = time.time()

    # Decide what we need to ask MOEX about.
    to_fetch: list[str] = []
    for b in bonds:
        if not b.isin:
            continue
        entry = cache.get(b.isin)
        if not entry or not _cache_entry_is_fresh(entry, now):
            to_fetch.append(b.isin)

    if to_fetch:
        logger.info(
            "Fetching MOEX default flags: %d uncached/stale ISINs (cache hit: %d/%d)",
            len(to_fetch),
            len(bonds) - len(to_fetch),
            len(bonds),
        )
        with (
            httpx.Client(
                transport=httpx.HTTPTransport(retries=2),
                timeout=_HTTP_TIMEOUT,
                follow_redirects=True,
            ) as client,
            ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex,
        ):
            futures = {ex.submit(_fetch_one, client, isin): isin for isin in to_fetch}
            for fut in as_completed(futures):
                isin = futures[fut]
                status = fut.result()
                if status is None:
                    # Keep absence of an entry (will retry next time).
                    continue
                cache[isin] = {
                    "ts": now,
                    "has_default": status.has_default,
                    "has_technical_default": status.has_technical_default,
                }
        _save_cache(cache)

    # Apply to bonds.
    for b in bonds:
        entry = cache.get(b.isin)
        if not entry:
            continue
        b.has_default = bool(entry.get("has_default", False))
        b.has_technical_default = bool(entry.get("has_technical_default", False))

    n_default = sum(1 for b in bonds if b.has_default)
    n_tech = sum(1 for b in bonds if b.has_technical_default)
    if n_default or n_tech:
        logger.info(
            "MOEX defaults flagged: %d in default, %d in technical default",
            n_default,
            n_tech,
        )
    return bonds
