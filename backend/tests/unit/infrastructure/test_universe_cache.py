"""Tests for shared enriched-universe cache."""

from __future__ import annotations

import time

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.infrastructure.bonds import universe_cache as cache


def setup_function() -> None:
    cache.invalidate_all()
    cache.configure_ttl(60.0)


def test_put_and_get_returns_cloned_bonds() -> None:
    bond = BondRecord(
        secid="A",
        isin="RU000A",
        name="Test",
        profile_scores={"normal": 55.0},
    )
    key = cache.BondCacheKey(
        key_rate=14.5,
        tax_rate=0.13,
        token_fingerprint="",
        kind="universe",
    )
    cache.put(key, [bond], "MOEX ISS API")

    loaded_bonds, source = cache.get(key) or ([], "")
    assert source == "MOEX ISS API"
    assert loaded_bonds[0] is not bond
    assert loaded_bonds[0].isin == "RU000A"

    loaded_bonds[0].is_favorite = True
    again, _ = cache.get(key) or ([], "")
    assert again[0].is_favorite is False

    loaded_bonds[0].profile_scores["normal"] = 99.0
    again, _ = cache.get(key) or ([], "")
    assert again[0].profile_scores["normal"] == 55.0


def test_get_expires_after_ttl(monkeypatch) -> None:
    cache.configure_ttl(0.01)
    key = cache.BondCacheKey(
        key_rate=14.5,
        tax_rate=0.13,
        token_fingerprint="",
        kind="universe",
    )
    cache.put(key, [BondRecord(secid="A", isin="RU000A", name="Test")], "src")

    time.sleep(0.02)
    assert cache.get(key) is None


def test_invalidate_all_clears_entries() -> None:
    key = cache.BondCacheKey(
        key_rate=14.5,
        tax_rate=0.13,
        token_fingerprint="",
        kind="screener",
        filter_by="effective",
        max_days=120,
        min_volume_rub=500_000,
    )
    cache.put(key, [BondRecord(secid="A", isin="RU000A", name="Test")], "src")
    cache.invalidate_all()
    assert cache.get(key) is None
