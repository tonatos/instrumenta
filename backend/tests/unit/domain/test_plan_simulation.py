"""Business invariants for event-sourced portfolio plan simulation."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from bond_monitor.domain.portfolio.cashflow import (
    CashflowEvent,
    cashflow_rows_with_balance,
    event_sort_key,
    running_cash_before_purchase,
)
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.portfolio.plan_models import MAX_AUTO_POSITIONS, REINVESTMENT_GAP_DAYS
from bond_monitor.domain.portfolio.planner import build_plan
from factories import (
    aa19dfd_live_portfolio,
    aa19dfd_live_universe,
    aa19dfd_portfolio,
    aa19dfd_universe,
    make_bond,
)

_bond = make_bond

_AA19DFD_LIVE_TODAY = date(2026, 7, 8)

_PHANTOM_SOURCES = frozenset(
    {
        PositionSourceType.REINVEST_MATURITY,
        PositionSourceType.REINVEST_PUT_OFFER,
        PositionSourceType.REINVEST_COUPON_CASH,
    }
)


def _build(
    portfolio: Portfolio,
    universe,
    *,
    today: date = date(2026, 7, 10),
    account_snapshot_money_rub: float | None = None,
) -> object:
    return build_plan(
        portfolio,
        universe,
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=account_snapshot_money_rub,
        assume_best_put_outcome=False,
    )


def _assert_api_cashflow_non_negative(plan: object) -> None:
    """Тот же контракт, что API → CashflowTable (balance_after_rub)."""
    rows = cashflow_rows_with_balance(plan.events, plan.initial_cash_rub)
    negatives = [
        row for row in rows if float(row["balance_after_rub"]) < -0.01
    ]
    assert not negatives, negatives[0] if negatives else None


def test_cashflow_api_balance_never_negative() -> None:
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    plan = _build(
        portfolio,
        aa19dfd_universe(),
        account_snapshot_money_rub=portfolio.cash_balance_rub,
    )
    _assert_api_cashflow_non_negative(plan)


def test_running_balance_never_negative() -> None:
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    plan = _build(
        portfolio,
        aa19dfd_universe(),
        account_snapshot_money_rub=portfolio.cash_balance_rub,
    )
    _assert_api_cashflow_non_negative(plan)


def test_same_day_maturity_before_deploy_purchase() -> None:
    """Погашение и deploy в один день: приток до покупок в журнальном порядке."""
    deploy_date = date(2026, 11, 21)
    events = [
        CashflowEvent(
            date=deploy_date,
            kind="coupon",
            amount_rub=5.0,
            description="c",
            related_isin="RU000A1",
            journal_seq=1,
        ),
        CashflowEvent(
            date=deploy_date,
            kind="maturity",
            amount_rub=418.0,
            description="m",
            related_isin="RU000A1",
            journal_seq=2,
        ),
        CashflowEvent(
            date=deploy_date,
            kind="purchase",
            amount_rub=-400.0,
            description="p",
            related_isin="RU000B1",
            journal_seq=3,
        ),
    ]
    rows = cashflow_rows_with_balance(events, initial_cash=100.0)
    assert all(float(row["balance_after_rub"]) >= -0.01 for row in rows)
    assert float(rows[-1]["balance_after_rub"]) == pytest.approx(123.0)

    wrong_order = sorted(events, key=event_sort_key)
    running = 100.0
    min_balance = running
    for event in wrong_order:
        running += event.amount_rub
        min_balance = min(min_balance, running)
    assert min_balance < 0


def test_aa19dfd_live_plan_balance() -> None:
    """Регрессия live aa19dfd (8 позиций): API cashflow без отрицательного баланса."""
    portfolio = aa19dfd_live_portfolio()
    plan = _build(
        portfolio,
        aa19dfd_live_universe(),
        today=_AA19DFD_LIVE_TODAY,
        account_snapshot_money_rub=portfolio.cash_balance_rub,
    )
    _assert_api_cashflow_non_negative(plan)


def test_no_coupons_after_position_maturity() -> None:
    """После погашения позиции купоны по её position_id не должны появляться."""
    today = date(2026, 7, 1)
    maturity = date(2026, 12, 1)
    bond = _bond(isin="RU000MAT", name="Maturing", maturity=maturity, ytm=25.0, score=90.0)
    repls = [
        _bond(
            isin=f"RU000R{i}",
            name=f"Repl {i}",
            maturity=date(2027, 3, 1 + i),
            ytm=20.0 + i,
            score=85.0 + i,
        )
        for i in range(8)
    ]
    portfolio = Portfolio(
        id="coupon-after-mat",
        name="Test",
        initial_amount_rub=200_000.0,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        api_trade_only=False,
        positions=[
            PortfolioPosition(
                isin=bond.isin,
                secid=bond.secid,
                name=bond.name,
                lots=50,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=49_500.0,
                maturity_date=maturity,
                offer_date=None,
                coupon_rate=20.0,
                coupon_period_days=91,
                next_coupon_date=date(2026, 9, 1),
                source=PositionSourceType.INITIAL,
            ),
        ],
    )
    plan = _build(portfolio, [bond, *repls], today=today)
    maturity_events = [
        e for e in plan.events if e.kind == "maturity" and e.related_isin == bond.isin
    ]
    assert maturity_events
    maturity_date = maturity_events[0].date
    later_coupons = [
        e
        for e in plan.events
        if e.kind == "coupon"
        and e.related_isin == bond.isin
        and e.date > maturity_date
    ]
    assert not later_coupons


def test_purchased_bonds_equal_redeemed_bonds_for_phantoms() -> None:
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    plan = _build(
        portfolio,
        aa19dfd_universe(),
        account_snapshot_money_rub=portfolio.cash_balance_rub,
    )
    initial_isins = {p.isin for p in portfolio.positions}
    purchased: dict[str, int] = {}
    redeemed: dict[str, int] = {}
    for event in plan.events:
        if not event.related_isin or event.related_isin in initial_isins:
            continue
        if event.kind == "purchase":
            purchased[event.related_isin] = purchased.get(event.related_isin, 0) + (
                event.lots or 0
            )
        elif event.kind in ("maturity", "put_offer"):
            redeemed[event.related_isin] = redeemed.get(event.related_isin, 0) + (
                event.bonds_count or 0
            )
    for isin, matured in redeemed.items():
        assert purchased.get(isin, 0) == matured, (
            f"{isin}: purchased {purchased.get(isin, 0)} vs matured {matured}"
        )


def test_deploy_spends_all_cash_after_maturity() -> None:
    """После deploy на дату погашения остаток ≤ стоимости одного лота."""
    today = date(2026, 7, 1)
    maturity = date(2026, 10, 8)
    purchase_date = maturity + timedelta(days=REINVESTMENT_GAP_DAYS)
    maturing = _bond(isin="RU000MAT", name="Maturing", maturity=maturity, ytm=28.0, score=95.0)
    repls = [
        _bond(
            isin=f"RU000R{i}",
            name=f"Repl {i}",
            maturity=date(2027, 3, 1 + i),
            ytm=22.0 + i,
            score=88.0 + i,
        )
        for i in range(8)
    ]
    portfolio = Portfolio(
        id="full-deploy",
        name="Test",
        initial_amount_rub=150_000.0,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        api_trade_only=False,
        positions=[
            PortfolioPosition(
                isin=maturing.isin,
                secid=maturing.secid,
                name=maturing.name,
                lots=70,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=69_300.0,
                maturity_date=maturity,
                offer_date=None,
                coupon_rate=20.0,
                coupon_period_days=91,
                next_coupon_date=date(2026, 10, 1),
                source=PositionSourceType.INITIAL,
            ),
        ],
    )
    plan = _build(portfolio, [maturing, *repls], today=today)
    purchases = [e for e in plan.events if e.kind == "purchase" and e.date == purchase_date]
    assert purchases
    events_before = [
        e for e in plan.events if not (e.kind == "purchase" and e.date == purchase_date)
    ]
    available = running_cash_before_purchase(events_before, purchase_date, plan.initial_cash_rub)
    spent = sum(-e.amount_rub for e in purchases)
    assert spent >= available * 0.95
    min_lot = min(
        b.price_per_lot_rub or 10_000.0 for b in [maturing, *repls] if b.price_per_lot_rub
    )
    assert available - spent <= min_lot + 1.0


def test_deploy_uses_auto_compose_for_reinvest() -> None:
    """Реинвест deploy вызывает auto_compose как при первоначальном наполнении."""
    today = date(2026, 7, 1)
    maturity = date(2026, 10, 8)
    maturing = _bond(isin="RU000MAT", name="Maturing", maturity=maturity, ytm=28.0, score=95.0)
    repls = [
        _bond(
            isin=f"RU000R{i}",
            name=f"Repl {i}",
            maturity=date(2027, 3, 1 + i),
            ytm=22.0 + i,
            score=88.0 + i,
        )
        for i in range(8)
    ]
    portfolio = Portfolio(
        id="compose-parity",
        name="Test",
        initial_amount_rub=120_000.0,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        api_trade_only=False,
        positions=[
            PortfolioPosition(
                isin=maturing.isin,
                secid=maturing.secid,
                name=maturing.name,
                lots=50,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=49_500.0,
                maturity_date=maturity,
                offer_date=None,
                coupon_rate=20.0,
                coupon_period_days=91,
                next_coupon_date=date(2026, 10, 1),
                source=PositionSourceType.INITIAL,
            ),
        ],
    )
    with patch("bond_monitor.domain.portfolio.deploy_cash.auto_compose") as mocked:
        mocked.side_effect = lambda **kwargs: ([], kwargs["initial_amount"], ["mock"])
        _build(portfolio, [maturing, *repls], today=today)
        assert mocked.called


def test_maturity_triggers_deploy_with_accumulated_coupons() -> None:
    """Deploy после погашения тратит весь кэш, включая купоны других бумаг."""
    today = date(2026, 7, 1)
    early_mat = date(2026, 9, 1)
    late_mat = date(2027, 2, 1)
    early = _bond(isin="RU000EAR", name="Early", maturity=early_mat, ytm=26.0, score=92.0)
    late = _bond(isin="RU000LAT", name="Late", maturity=late_mat, ytm=24.0, score=90.0)
    repls = [
        _bond(
            isin=f"RU000R{i}",
            name=f"Repl {i}",
            maturity=date(2027, 5, 1 + i),
            ytm=20.0 + i,
            score=85.0 + i,
        )
        for i in range(8)
    ]
    deploy_date = early_mat + timedelta(days=REINVESTMENT_GAP_DAYS)
    portfolio = Portfolio(
        id="accum-coupons",
        name="Test",
        initial_amount_rub=200_000.0,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        api_trade_only=False,
        positions=[
            PortfolioPosition(
                isin=early.isin,
                secid=early.secid,
                name=early.name,
                lots=40,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=39_600.0,
                maturity_date=early_mat,
                offer_date=None,
                coupon_rate=18.0,
                coupon_period_days=91,
                next_coupon_date=date(2026, 8, 1),
                source=PositionSourceType.INITIAL,
            ),
            PortfolioPosition(
                isin=late.isin,
                secid=late.secid,
                name=late.name,
                lots=60,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=59_400.0,
                maturity_date=late_mat,
                offer_date=None,
                coupon_rate=16.0,
                coupon_period_days=182,
                next_coupon_date=date(2026, 12, 1),
                source=PositionSourceType.INITIAL,
            ),
        ],
    )
    plan = _build(portfolio, [early, late, *repls], today=today)
    purchases = [e for e in plan.events if e.kind == "purchase" and e.date == deploy_date]
    assert purchases
    events_before = [
        e for e in plan.events if not (e.kind == "purchase" and e.date == deploy_date)
    ]
    available = running_cash_before_purchase(events_before, deploy_date, plan.initial_cash_rub)
    coupon_inflows = sum(
        e.amount_rub
        for e in events_before
        if e.kind == "coupon" and e.date <= deploy_date
    )
    assert coupon_inflows > 0
    spent = sum(-e.amount_rub for e in purchases)
    assert spent >= available * 0.9


def test_synthetic_high_ytm_xirr_sanity() -> None:
    """Синтетический портфель ~30% YTM → XIRR net существенно выше ключевой ставки."""
    today = date(2026, 1, 1)
    horizon = date(2027, 1, 1)
    bonds = [
        _bond(
            isin=f"RU000H{i}",
            name=f"High {i}",
            maturity=date(2026, 6, 15) + timedelta(days=30 * i),
            ytm=30.0,
            score=95.0,
            coupon_rate=28.0,
            coupon_period_days=91,
            next_coupon_date=date(2026, 4, 1),
        )
        for i in range(6)
    ]
    portfolio = Portfolio(
        id="high-ytm",
        name="High YTM",
        initial_amount_rub=600_000.0,
        horizon_date=horizon,
        risk_profile=RiskProfile.AGGRESSIVE,
        api_trade_only=False,
        positions=[],
    )
    plan = _build(portfolio, bonds, today=today)
    assert plan.effective_annual_return_pct is not None
    assert plan.effective_annual_return_pct >= 14.0


def test_aa19dfd_regression_no_phantom_redemptions() -> None:
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    plan = _build(
        portfolio,
        aa19dfd_universe(),
        account_snapshot_money_rub=portfolio.cash_balance_rub,
    )
    assert plan.effective_annual_return_pct is None or plan.effective_annual_return_pct < 80.0
    initial_isins = {p.isin for p in portfolio.positions}
    purchased: dict[str, int] = {}
    redeemed: dict[str, int] = {}
    for event in plan.events:
        if not event.related_isin or event.related_isin in initial_isins:
            continue
        if event.kind == "purchase":
            purchased[event.related_isin] = purchased.get(event.related_isin, 0) + (
                event.lots or 0
            )
        elif event.kind in ("maturity", "put_offer"):
            redeemed[event.related_isin] = redeemed.get(event.related_isin, 0) + (
                event.bonds_count or 0
            )
    for isin in redeemed:
        assert purchased.get(isin, 0) == redeemed[isin]
