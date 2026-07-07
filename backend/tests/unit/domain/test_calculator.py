"""Unit tests for portfolio hold calculator."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.calculator import calculate_bond_hold, calculate_portfolio_budget


def _bond(
    *,
    secid: str = "TEST01",
    price: float = 98.0,
    coupon_rate: float = 20.0,
    coupon_period_days: int = 182,
    next_coupon: date = date(2026, 8, 1),
    end: date = date(2027, 1, 1),
    offer: date | None = None,
    offer_price_pct: float | None = None,
) -> BondRecord:
    return BondRecord(
        secid=secid,
        isin=secid,
        name="Test bond",
        last_price=price,
        face_value=1000.0,
        lot_size=1,
        coupon_rate=coupon_rate,
        coupon_period_days=coupon_period_days,
        next_coupon_date=next_coupon,
        maturity_date=end if offer is None else max(end, offer),
        offer_date=offer,
        offer_price_pct=offer_price_pct,
        effective_date=offer or end,
    )


def test_calculate_bond_hold_includes_coupons_and_redemption_without_tax() -> None:
    today = date(2026, 7, 1)
    bond = _bond(
        price=98.0,
        coupon_rate=20.0,
        coupon_period_days=182,
        next_coupon=date(2026, 8, 1),
        end=date(2027, 1, 1),
    )
    result = calculate_bond_hold(bond, lots=10, today=today)
    assert result is not None
    assert result.invested_rub == 9_800.0
    assert result.coupon_income_rub > 0
    assert result.redemption_rub == 10_000.0
    assert result.profit_rub > 200.0
    assert abs(
        result.profit_rub - (result.coupon_income_rub + result.redemption_rub - result.invested_rub)
    ) < 0.02


def test_calculate_bond_hold_uses_offer_date_and_price() -> None:
    today = date(2026, 7, 1)
    bond = _bond(
        price=99.0,
        coupon_rate=12.0,
        coupon_period_days=30,
        next_coupon=date(2026, 7, 15),
        end=date(2027, 7, 1),
        offer=date(2026, 7, 20),
        offer_price_pct=100.0,
    )
    result = calculate_bond_hold(bond, lots=5, today=today)
    assert result is not None
    assert result.hold_days == 19
    assert result.redemption_rub == 5_000.0
    assert result.coupon_income_rub > 0


def test_calculate_portfolio_budget_splits_budget_across_bonds() -> None:
    today = date(2026, 7, 1)
    bonds = [
        _bond(secid="A1", price=100.0, end=date(2027, 1, 1)),
        _bond(secid="B2", price=100.0, end=date(2027, 6, 1)),
    ]
    result = calculate_portfolio_budget(bonds, budget_rub=20_000, today=today)
    assert len(result.positions) == 2
    assert result.total_invested_rub > 0
    assert abs(result.total_profit_rub - sum(p.profit_rub for p in result.positions)) < 0.02
    assert result.portfolio_yield_pct is not None
