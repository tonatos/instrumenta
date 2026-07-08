"""Tests for build_trading_plan and operations lookback."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from bond_monitor.application.trading.advise_use_case import operations_from_date
from bond_monitor.application.trading.plan_from_broker import build_trading_plan
from factories import make_account_snapshot, make_bond, make_portfolio
from bond_monitor.domain.trading.ports import BrokerBondPosition
from bond_monitor.domain.shared.money import PriceUnitPct, Rub


def _bond_position(*, figi: str, lots: int, quantity: int) -> BrokerBondPosition:
    return BrokerBondPosition(
        figi=figi,
        instrument_uid="uid-hold",
        ticker="SU26238",
        quantity=quantity,
        lots=lots,
        blocked=0,
        current_price_pct=PriceUnitPct(96.0),
        current_nkd_rub=Rub(5.0),
        average_price_pct=PriceUnitPct(95.0),
    )


def test_operations_from_date_uses_year_lookback_not_trading_started_at() -> None:
    portfolio = make_portfolio(trading_started_at="2026-07-08T10:00:00+00:00")
    today = date(2026, 7, 8)
    from_date = operations_from_date(portfolio, today=today)
    assert from_date == today - timedelta(days=365)


def test_build_trading_plan_produces_cashflow_from_broker_holdings() -> None:
    maturity = date.today() + timedelta(days=180)
    bond = make_bond(
        isin="RU000A2",
        figi="FIGI-CF",
        maturity=maturity,
        coupon_rate=12.0,
        coupon_period_days=30,
        next_coupon_date=date.today() + timedelta(days=30),
    )
    portfolio = make_portfolio(horizon_date=date.today() + timedelta(days=365))
    snapshot = make_account_snapshot(
        10_000.0,
        bond_positions={"FIGI-CF": _bond_position(figi="FIGI-CF", lots=1, quantity=1)},
    )
    plan = build_trading_plan(
        portfolio,
        snapshot,
        [bond],
        key_rate=16.0,
        tax_rate=0.13,
        today=date.today(),
    )
    assert plan.events
    assert plan.invested_capital_rub > 0
