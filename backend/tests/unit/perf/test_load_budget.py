"""Performance regression tests with mocked I/O."""

from __future__ import annotations

import time
from datetime import date
from unittest.mock import patch

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.trading.plan_from_broker import build_trading_plan
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, RiskProfile
from bond_monitor.domain.portfolio.planner import build_plan
from bond_monitor.infrastructure.bonds import universe_cache
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from factories import make_account_snapshot, make_bond, make_portfolio


def _large_universe(count: int = 500) -> list[BondRecord]:
    return [
        make_bond(
            isin=f"RU000A{i:04d}",
            secid=f"SEC{i:04d}",
            maturity=date(2026, 6, 1),
            price=98.0 + (i % 5),
            ytm=15.0 + (i % 10) * 0.1,
            score=70.0 + (i % 20),
        )
        for i in range(count)
    ]


def test_load_universe_uses_shared_cache_without_duplicate_fetch(monkeypatch) -> None:
    universe_cache.invalidate_all()
    calls = {"count": 0}

    def fake_fetch():
        calls["count"] += 1
        return [BondRecord(secid="A", isin="RU000A", name="Test")]

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.fetch_all_bonds_unfiltered",
        fake_fetch,
    )
    monkeypatch.setattr(
        BondService,
        "_enrich_and_score",
        lambda self, bonds: (bonds, "MOEX ISS API"),
    )

    BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="").load_universe()
    BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="").load_universe()

    assert calls["count"] == 1


def test_build_plan_completes_within_budget() -> None:
    universe = _large_universe(500)
    portfolio = make_portfolio(
        horizon_date=date(2027, 12, 31),
        risk_profile=RiskProfile.AGGRESSIVE,
        positions=[],
    )
    t0 = time.perf_counter()
    build_plan(
        portfolio,
        universe,
        today=date.today(),
        key_rate=14.5,
        tax_rate=0.13,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5


def test_build_trading_plan_completes_within_budget() -> None:
    universe = _large_universe(500)
    portfolio = make_portfolio(
        horizon_date=date(2027, 12, 31),
        risk_profile=RiskProfile.AGGRESSIVE,
        positions=[],
    )
    portfolio.mode = "trading"
    portfolio.account_id = "acc-1"
    snapshot = broker_snapshot_from_infrastructure(make_account_snapshot(100_000.0))

    t0 = time.perf_counter()
    build_trading_plan(
        portfolio,
        snapshot,
        universe,
        key_rate=14.5,
        tax_rate=0.13,
        today=date.today(),
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.15
