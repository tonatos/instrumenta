"""Smoke-тесты `distribute_top_up` для simulation/plan UI."""

from __future__ import annotations

from datetime import date

import pytest

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import Portfolio, RiskProfile
from bond_monitor.domain.portfolio.planner import distribute_top_up


def _bond(isin: str) -> BondRecord:
    bond = BondRecord(
        secid=isin[:6],
        isin=isin,
        name=f"Bond {isin[-3:]}",
        maturity_date=date(2026, 12, 31),
        last_price=100.0,
        face_value=1000.0,
        lot_size=1,
        coupon_rate=10.0,
        coupon_period_days=180,
        volume_rub=1_000_000.0,
        liquidity_flag=True,
        credit_rating="ruAAA",
        risk_level=RiskLevel.LOW,
        ytm=12.0,
        ytm_net=10.0,
    )
    bond.accrued_interest = 0.0
    return bond


def _portfolio(initial: float = 100_000.0) -> Portfolio:
    return Portfolio(
        name="T",
        initial_amount_rub=initial,
        horizon_date=date(2026, 12, 31),
        risk_profile=RiskProfile.NORMAL,
        api_trade_only=False,
    )


def test_distribute_zero_amount() -> None:
    allocs, _ = distribute_top_up(
        portfolio=_portfolio(),
        universe=[_bond("RU000A1")],
        top_up_amount_rub=0.0,
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert not allocs


def test_distribute_picks_top_scored_bonds() -> None:
    universe = [_bond(f"RU000A{i:03d}") for i in range(5)]
    allocs, _ = distribute_top_up(
        portfolio=_portfolio(initial=10_000.0),
        universe=universe,
        top_up_amount_rub=50_000.0,
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert allocs
    assert sum(a.estimated_amount_rub for a in allocs) <= 50_000.0


def test_top_up_total_budget_uses_initial_plus_input() -> None:
    from bond_monitor.domain.portfolio.top_up_distribution import top_up_total_budget_rub

    p = _portfolio(initial=20_000.0)
    assert top_up_total_budget_rub(p, 180_000.0) == pytest.approx(200_000.0)
