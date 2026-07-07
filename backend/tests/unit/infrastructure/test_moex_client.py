"""MOEX client unit tests (no network)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.infrastructure.moex import client as moex_client
from bond_monitor.infrastructure.moex.client import (
    _build_bond_record,
    _filter_volume_rub,
    _MoexCacheBundle,
    _prev_volumes_from_bundle,
    fetch_all_bonds,
)


def _raw_row(
    *,
    val_today: float = 0.0,
    secid: str = "TEST001",
    isin: str = "RU000A0TEST01",
) -> dict:
    today = date.today()
    maturity = (today + timedelta(days=60)).isoformat()
    return {
        "SECID": secid,
        "ISIN": isin,
        "SHORTNAME": "Тест 001",
        "FACEUNIT": "SUR",
        "MATDATE": maturity,
        "FACEVALUE": 1000.0,
        "LOTSIZE": 1,
        "VALTODAY": val_today,
    }


def test_build_bond_record_keeps_today_volume_for_display() -> None:
    bond = _build_bond_record("RU000A0TEST01", _raw_row(val_today=12_345.0), date.today())
    assert bond is not None
    assert bond.volume_rub == 12_345.0


def test_build_bond_record_sets_prev_volume_when_provided() -> None:
    bond = _build_bond_record(
        "RU000A0TEST01",
        _raw_row(val_today=0.0),
        date.today(),
        prev_volume_rub=900_000.0,
    )
    assert bond is not None
    assert bond.volume_rub == 0.0
    assert bond.prev_volume_rub == 900_000.0


def test_filter_volume_rub_prefers_prev_over_today() -> None:
    bond = BondRecord(
        secid="X",
        isin="RU000A0X",
        volume_rub=5_000_000.0,
        prev_volume_rub=100_000.0,
    )
    assert _filter_volume_rub(bond) == 100_000.0


def test_filter_volume_rub_falls_back_to_today_when_prev_missing() -> None:
    bond = BondRecord(secid="X", isin="RU000A0X", volume_rub=250_000.0)
    assert _filter_volume_rub(bond) == 250_000.0


def test_prev_volumes_from_bundle_uses_yesterday_cache_on_new_day() -> None:
    yesterday = date.today() - timedelta(days=1)
    old = _MoexCacheBundle(
        saved_date=yesterday,
        bonds={
            "RU000A0AAA": _raw_row(val_today=1_200_000.0, isin="RU000A0AAA"),
            "RU000A0BBB": _raw_row(val_today=50_000.0, isin="RU000A0BBB"),
        },
        prev_volumes={},
    )
    prev = _prev_volumes_from_bundle(old, today=date.today())
    assert prev["RU000A0AAA"] == 1_200_000.0
    assert prev["RU000A0BBB"] == 50_000.0


def test_prev_volumes_from_bundle_keeps_existing_on_same_day() -> None:
    today = date.today()
    bundle = _MoexCacheBundle(
        saved_date=today,
        bonds={"RU000A0AAA": _raw_row(val_today=10_000.0)},
        prev_volumes={"RU000A0AAA": 800_000.0},
    )
    prev = _prev_volumes_from_bundle(bundle, today=today)
    assert prev == {"RU000A0AAA": 800_000.0}


def test_fetch_all_bonds_filters_by_prev_volume_not_today(monkeypatch: pytest.MonkeyPatch) -> None:
    today = date.today()
    merged = {
        "RU000A0LIQUID": _raw_row(val_today=0.0, isin="RU000A0LIQUID"),
        "RU000A0ILLIQ": _raw_row(val_today=9_000_000.0, isin="RU000A0ILLIQ"),
    }
    bundle = _MoexCacheBundle(
        saved_date=today,
        bonds=merged,
        prev_volumes={
            "RU000A0LIQUID": 1_000_000.0,
            "RU000A0ILLIQ": 10_000.0,
        },
    )
    monkeypatch.setattr(moex_client, "_load_or_fetch_bundle", lambda: bundle)

    bonds = fetch_all_bonds(max_days=120, min_volume_rub=500_000.0)

    isins = {b.isin for b in bonds}
    assert "RU000A0LIQUID" in isins
    assert "RU000A0ILLIQ" not in isins
    liquid = next(b for b in bonds if b.isin == "RU000A0LIQUID")
    assert liquid.volume_rub == 0.0
    assert liquid.prev_volume_rub == 1_000_000.0
