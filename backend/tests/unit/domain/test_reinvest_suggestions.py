"""Reinvest suggestion timing — watch vs actionable."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    DEFAULT_PLANNING_POLICY,
)
from bond_monitor.domain.trading.advisory import (
    build_reinvest_suggestions,
    build_reinvest_watch_suggestions,
    effective_trading_positions,
)
from bond_monitor.domain.trading.ports import BrokerBondPosition
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from factories import make_account_snapshot, make_bond, make_portfolio


def _portfolio_with_maturing_bond(*, maturity: date, today: date):
    source = make_bond(
        isin="RU000SRC1",
        name="СамолетP13",
        figi="FIGI-SRC",
        maturity=maturity,
        price=100.0,
        volume_rub=5_000_000.0,
    )
    replacement = make_bond(
        isin="RU000NEW1",
        name="Replacement",
        figi="FIGI-NEW",
        maturity=date(2027, 9, 1),
        price=99.0,
        volume_rub=5_000_000.0,
    )
    portfolio = make_portfolio(
        initial_amount_rub=200_000.0,
        horizon_date=date(2028, 1, 1),
    )
    portfolio.id = "portfolio-reinvest"
    snapshot = make_account_snapshot(
        10_000.0,
        bond_positions={
            "FIGI-SRC": BrokerBondPosition(
                figi="FIGI-SRC",
                instrument_uid="uid-src",
                ticker="SRC",
                quantity=10,
                lots=10,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
    )
    positions = effective_trading_positions(
        portfolio,
        snapshot,
        [source, replacement],
        purchase_date=today,
    )
    return portfolio, positions, [source, replacement], today


def test_reinvest_before_maturity_is_watch_only() -> None:
    today = date(2026, 7, 13)
    maturity = date(2026, 7, 24)
    portfolio, positions, universe, today = _portfolio_with_maturing_bond(
        maturity=maturity,
        today=today,
    )

    watch = build_reinvest_watch_suggestions(
        portfolio,
        positions,
        universe,
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        policy=DEFAULT_BOND_SELECTION_POLICY,
        planning=DEFAULT_PLANNING_POLICY,
    )
    actionable = build_reinvest_suggestions(
        portfolio,
        positions,
        universe,
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        policy=DEFAULT_BOND_SELECTION_POLICY,
        planning=DEFAULT_PLANNING_POLICY,
    )

    assert len(watch) == 1
    assert watch[0].kind == "reinvest_watch"
    assert watch[0].due_date == maturity
    assert actionable == []


def test_reinvest_on_maturity_day_is_actionable() -> None:
    today = date(2026, 7, 24)
    portfolio, positions, universe, today = _portfolio_with_maturing_bond(
        maturity=today,
        today=today,
    )

    watch = build_reinvest_watch_suggestions(
        portfolio,
        positions,
        universe,
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        policy=DEFAULT_BOND_SELECTION_POLICY,
        planning=DEFAULT_PLANNING_POLICY,
    )
    actionable = build_reinvest_suggestions(
        portfolio,
        positions,
        universe,
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        policy=DEFAULT_BOND_SELECTION_POLICY,
        planning=DEFAULT_PLANNING_POLICY,
    )

    assert watch == []
    assert len(actionable) == 1
    assert actionable[0].kind == "reinvest"
