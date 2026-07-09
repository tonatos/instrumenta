"""Shared in-process cache for enriched bond universes."""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Literal

from bond_monitor.domain.bonds.models import BondRecord

CacheKind = Literal["universe", "screener"]

_DEFAULT_TTL_SEC = 120.0

_lock = threading.Lock()
_cache: dict[BondCacheKey, _CacheEntry] = {}
_ttl_sec = _DEFAULT_TTL_SEC


@dataclass(frozen=True)
class BondCacheKey:
    key_rate: float
    tax_rate: float
    token_fingerprint: str
    kind: CacheKind
    filter_by: str = ""
    max_days: int = 0
    min_volume_rub: float = 0.0


@dataclass
class _CacheEntry:
    bonds: list[BondRecord]
    source: str
    cached_at: float


def configure_ttl(seconds: float) -> None:
    """Set shared cache TTL (used from settings at startup / tests)."""
    global _ttl_sec
    _ttl_sec = seconds


def token_fingerprint(token: str | None) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def get(key: BondCacheKey) -> tuple[list[BondRecord], str] | None:
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if (now - entry.cached_at) >= _ttl_sec:
            del _cache[key]
            return None
        return _clone_bonds(entry.bonds), entry.source


def put(key: BondCacheKey, bonds: list[BondRecord], source: str) -> None:
    with _lock:
        _cache[key] = _CacheEntry(
            bonds=_clone_bonds(bonds),
            source=source,
            cached_at=time.monotonic(),
        )


def invalidate_all() -> None:
    with _lock:
        _cache.clear()


def _clone_bonds(bonds: list[BondRecord]) -> list[BondRecord]:
    return [copy.copy(bond) for bond in bonds]
