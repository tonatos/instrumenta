"""Тесты ограничений кэша в режиме торговли."""

from __future__ import annotations

from datetime import date

import pytest

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    AccountKind,
    PendingOperation,
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.portfolio.planner import build_plan
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub, order_amount_rub
from bond_monitor.domain.trading.cash_constraints import (
    available_cash_for_new_purchases_rub,
    estimate_pending_purchase_commitment_rub,
)


def _bond(isin: str = "RU000SAMO", *, price: float = 94.77) -> BondRecord:
    bond = BondRecord(
        secid="SAMO13",
        isin=isin,
        name="СамолетP13",
        maturity_date=date(2027, 6, 1),
        last_price=price,
        face_value=1000.0,
        lot_size=1,
        coupon_rate=12.0,
        coupon_period_days=180,
        volume_rub=1_000_000.0,
        liquidity_flag=True,
        credit_rating="ruBBB",
        risk_level=RiskLevel.LOW,
        ytm=15.0,
        ytm_net=13.0,
    )
    bond.accrued_interest = 0.0
    return bond


def _position(*, lots: int = 11, actual_lots: int = 0) -> PortfolioPosition:
    return PortfolioPosition(
        isin="RU000SAMO",
        secid="SAMO13",
        name="СамолетP13",
        lots=lots,
        lot_size=1,
        purchase_clean_price_pct=94.77,
        purchase_dirty_price_rub=947.7,
        purchase_aci_rub=0.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=947.7 * lots,
        coupon_rate=12.0,
        face_value=1000.0,
        maturity_date=date(2027, 6, 1),
        offer_date=None,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        figi="FIGI_SAMO",
        actual_lots=actual_lots,
    )


def _trading_portfolio(*, lots: int = 11, actual_lots: int = 0) -> Portfolio:
    p = Portfolio(
        name="Trading cash",
        initial_amount_rub=20_000.0,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.NORMAL,
        mode=PortfolioMode.TRADING,
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
    )
    p.positions = [_position(lots=lots, actual_lots=actual_lots)]
    return p


def test_estimate_pending_commitment_counts_unfilled_initial_gap() -> None:
    portfolio = _trading_portfolio(lots=11, actual_lots=0)
    universe = {"RU000SAMO": _bond()}
    committed = estimate_pending_purchase_commitment_rub(portfolio, universe)
    assert committed == pytest.approx(11 * 947.7, rel=0.01)


def test_available_cash_subtracts_pending_commitment() -> None:
    portfolio = _trading_portfolio(lots=11, actual_lots=0)
    universe = {"RU000SAMO": _bond()}
    free = available_cash_for_new_purchases_rub(4779.0, portfolio, universe)
    # 4779 * 0.995 - 11*947.7 ≈ отрицательное → 0
    assert free == 0.0


def test_build_plan_trading_cashflow_never_drives_cash_below_zero() -> None:
    """Сценарий пользователя: 11 лотов при 4 779 ₽ на счёте."""
    portfolio = _trading_portfolio(lots=11, actual_lots=0)
    bond = _bond()
    today = date(2026, 8, 8)

    plan = build_plan(
        portfolio,
        [bond],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=Rub(4779.0),
    )

    purchases = [e for e in plan.events if e.kind == "purchase" and e.date >= today]
    total_purchase = sum(-e.amount_rub for e in purchases)
    assert total_purchase <= 4779.0 + 0.01

    running = 4779.0
    for event in sorted(plan.events, key=lambda e: (e.date, e.kind)):
        running += event.amount_rub
        assert running >= -0.01, f"cash went negative after {event.description}"

    assert plan.final_cash_balance_rub >= -0.01


def test_estimate_pending_commitment_top_up_fallback_includes_accrued_interest() -> None:
    """top_up_buy без estimated_amount_rub резервирует кэш с учётом НКД."""
    bond = _bond()
    bond.accrued_interest = 25.0
    portfolio = _trading_portfolio(lots=0, actual_lots=0)
    portfolio.positions = []
    portfolio.pending_operations = [
        PendingOperation(
            kind="top_up_buy",
            isin="RU000SAMO",
            name="СамолетP13",
            lots=3,
            figi="FIGI_SAMO",
            suggested_price_pct=94.77,
            top_up_batch_id="batch-1",
        )
    ]
    committed = estimate_pending_purchase_commitment_rub(portfolio, {"RU000SAMO": bond})
    expected = float(
        order_amount_rub(
            price_pct=PriceUnitPct(94.77),
            face_value=1000.0,
            lot_size=1,
            lots=Lots(3),
            aci_rub=25.0,
        )
    )
    assert committed == pytest.approx(expected)
    assert committed > 3 * 947.7


def test_build_plan_initial_buy_gap_uses_live_dirty_price() -> None:
    """Догоняющая покупка в TRADING оценивается по текущей грязной цене из universe."""
    portfolio = _trading_portfolio(lots=2, actual_lots=0)
    bond = _bond()
    bond.accrued_interest = 30.0
    today = date(2026, 8, 8)

    plan = build_plan(
        portfolio,
        [bond],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=Rub(50_000.0),
    )

    purchases = [e for e in plan.events if e.kind == "purchase" and e.date >= today]
    assert len(purchases) == 1
    live_dirty_per_bond = 947.7 + 30.0
    assert purchases[0].amount_rub == pytest.approx(-2 * live_dirty_per_bond)


def test_build_plan_simulation_cashflow_never_drives_cash_below_zero() -> None:
    """Симуляция: купонный реинвест не должен уводить cashflow в минус."""
    portfolio = Portfolio(
        name="Simulation cash",
        initial_amount_rub=20_000.0,
        horizon_date=date(2027, 7, 7),
        risk_profile=RiskProfile.AGGRESSIVE,
        mode=PortfolioMode.SIMULATION,
        api_trade_only=True,
    )
    portfolio.cash_balance_rub = 3_248.54
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A107RZ0",
            secid="RU000A107RZ0",
            name="СамолетP13",
            lots=6,
            lot_size=1,
            purchase_clean_price_pct=93.34,
            purchase_dirty_price_rub=939.15,
            purchase_aci_rub=5.75,
            purchase_date=date(2026, 7, 7),
            purchase_amount_rub=5_634.9,
            coupon_rate=21.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 24),
            offer_date=None,
            coupon_period_days=30,
            source=PositionSourceType.INITIAL,
        ),
        PortfolioPosition(
            isin="RU000A100PB0",
            secid="RU000A100PB0",
            name="ЖКХРСЯ БО1",
            lots=5,
            lot_size=1,
            purchase_clean_price_pct=99.44,
            purchase_dirty_price_rub=1_039.14,
            purchase_aci_rub=44.74,
            purchase_date=date(2026, 7, 7),
            purchase_amount_rub=5_195.7,
            coupon_rate=23.0,
            face_value=1000.0,
            maturity_date=date(2026, 7, 28),
            offer_date=None,
            coupon_period_days=91,
            source=PositionSourceType.INITIAL,
        ),
    ]
    samo = _bond(isin="RU000A107RZ0", price=93.34)
    samo.coupon_rate = 21.0
    samo.coupon_period_days = 30
    samo.maturity_date = date(2027, 1, 24)
    zhkh = _bond(isin="RU000A100PB0", price=99.44)
    zhkh.coupon_rate = 23.0
    zhkh.coupon_period_days = 91
    zhkh.maturity_date = date(2026, 7, 28)
    today = date(2026, 7, 7)

    plan = build_plan(
        portfolio,
        [samo, zhkh],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
    )

    running = portfolio.initial_amount_rub
    for event in sorted(plan.events, key=lambda e: (e.date, e.kind)):
        running += event.amount_rub
        assert running >= -0.01, f"cash went negative after {event.description}"

    assert plan.final_cash_balance_rub >= -0.01
    for point in plan.value_timeline:
        assert point.cash_rub >= -0.01


def test_build_plan_skips_purchase_covered_by_top_up_pending() -> None:
    portfolio = _trading_portfolio(lots=16, actual_lots=5)
    portfolio.pending_operations = [
        PendingOperation(
            kind="top_up_buy",
            isin="RU000SAMO",
            name="СамолетP13",
            lots=11,
            figi="FIGI_SAMO",
            estimated_amount_rub=10_425.0,
            top_up_batch_id="batch-1",
        )
    ]
    bond = _bond()
    today = date(2026, 8, 8)

    plan = build_plan(
        portfolio,
        [bond],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=Rub(4779.0),
    )

    purchases = [e for e in plan.events if e.kind == "purchase" and e.date >= today]
    assert not purchases
