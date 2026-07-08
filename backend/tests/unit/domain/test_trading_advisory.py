"""Unit tests for stateless trading advisory."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.advisory import advise, build_holdings, build_holdings_cashflow
from bond_monitor.domain.trading.ports import BrokerBondPosition
from factories import make_account_snapshot, make_bond, make_portfolio


def _bond_position(
    *,
    figi: str = "FIGI-HOLD",
    lots: int = 2,
    quantity: int = 2,
) -> BrokerBondPosition:
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


def test_build_holdings_from_snapshot_and_universe() -> None:
    bond = make_bond(isin="RU000A1", name="Hold Bond", figi="FIGI-HOLD", ytm=17.5)
    snapshot = make_account_snapshot(
        50_000.0,
        bond_positions={"FIGI-HOLD": _bond_position()},
    )
    holdings = build_holdings(snapshot, [bond])
    assert len(holdings) == 1
    assert holdings[0].isin == "RU000A1"
    assert holdings[0].lots == 2
    assert holdings[0].ytm == 17.5
    assert holdings[0].market_value_rub is not None
    assert holdings[0].market_value_rub > 0


def test_advise_builds_cashflow_from_holdings() -> None:
    maturity = date.today() + timedelta(days=180)
    bond = make_bond(
        isin="RU000A2",
        name="Cashflow Bond",
        figi="FIGI-CF",
        maturity=maturity,
        coupon_rate=12.0,
        coupon_period_days=30,
        next_coupon_date=date.today() + timedelta(days=30),
    )
    bond.coupon_rate = 12.0
    bond.coupon_period_days = 30
    bond.next_coupon_date = date.today() + timedelta(days=30)
    portfolio = make_portfolio(
        horizon_date=date.today() + timedelta(days=365),
        risk_profile=RiskProfile.NORMAL,
    )
    snapshot = make_account_snapshot(
        10_000.0,
        bond_positions={"FIGI-CF": _bond_position(figi="FIGI-CF", lots=1, quantity=1)},
    )
    advice = advise(
        portfolio,
        snapshot,
        active_orders=[],
        operations=[],
        universe=[bond],
        key_rate=16.0,
        tax_rate=0.13,
        today=date.today(),
    )
    assert advice.holdings
    assert advice.cashflow
    coupon_events = [e for e in advice.cashflow if e.kind == "coupon"]
    maturity_events = [e for e in advice.cashflow if e.kind == "maturity"]
    assert coupon_events
    assert maturity_events


def test_advise_suggests_buy_when_free_cash_available() -> None:
    bond_a = make_bond(isin="RU000A3", name="Cheap Bond", figi="FIGI-A", price=95.0, ytm=20.0)
    bond_b = make_bond(
        isin="RU000B1",
        name="Candidate",
        figi="FIGI-B",
        price=96.0,
        ytm=22.0,
        score=90.0,
        maturity=date.today() + timedelta(days=200),
    )
    portfolio = make_portfolio(
        initial_amount_rub=100_000.0,
        horizon_date=date.today() + timedelta(days=400),
        risk_profile=RiskProfile.NORMAL,
        account_kind="sandbox",
    )
    snapshot = make_account_snapshot(
        80_000.0,
        bond_positions={"FIGI-A": _bond_position(figi="FIGI-A")},
    )
    advice = advise(
        portfolio,
        snapshot,
        active_orders=[],
        operations=[],
        universe=[bond_a, bond_b],
        key_rate=16.0,
        tax_rate=0.13,
        today=date.today(),
    )
    buy_suggestions = [s for s in advice.suggestions if s.kind == "buy"]
    assert buy_suggestions
    assert buy_suggestions[0].lots >= 1
    assert buy_suggestions[0].suggested_price_pct is not None


def test_advise_put_offer_reminder_for_near_offer() -> None:
    offer_date = date.today() + timedelta(days=10)
    bond = make_bond(
        isin="RU000PO",
        name="Put Offer Bond",
        figi="FIGI-PO",
        maturity=date.today() + timedelta(days=500),
    )
    bond.offer_date = offer_date
    bond.offer_submission_start = date.today() - timedelta(days=5)
    bond.offer_submission_end = offer_date - timedelta(days=1)
    bond.offer_price_pct = 100.0
    portfolio = make_portfolio(horizon_date=date.today() + timedelta(days=600))
    snapshot = make_account_snapshot(
        5_000.0,
        bond_positions={"FIGI-PO": _bond_position(figi="FIGI-PO")},
    )
    advice = advise(
        portfolio,
        snapshot,
        active_orders=[],
        operations=[],
        universe=[bond],
        key_rate=16.0,
        tax_rate=0.13,
        today=date.today(),
    )
    reminders = [s for s in advice.suggestions if s.kind == "put_offer_reminder"]
    assert len(reminders) == 1
    assert reminders[0].chat_template
    assert reminders[0].urgency in ("soon", "critical")


def test_advise_includes_performance_and_active_orders() -> None:
    bond = make_bond(isin="RU000P1", figi="FIGI-P1")
    portfolio = make_portfolio(
        trading_started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        account_kind="sandbox",
    )
    snapshot = make_account_snapshot(
        20_000.0,
        bond_positions={"FIGI-P1": _bond_position(figi="FIGI-P1")},
    )
    from bond_monitor.domain.trading.ports import BrokerActiveOrder

    active = [
        BrokerActiveOrder(
            order_id="ord-1",
            request_uid="req-1",
            figi="FIGI-P1",
            direction="BUY",
            lots_requested=1,
            lots_executed=0,
            status="EXECUTION_REPORT_STATUS_NEW",
            price_pct=96.0,
            total_order_amount_rub=1000.0,
            initial_commission_rub=1.0,
        )
    ]
    advice = advise(
        portfolio,
        snapshot,
        active_orders=active,
        operations=[],
        universe=[bond],
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert advice.performance is not None
    assert len(advice.active_orders) == 1
    assert advice.available_money_rub == 20_000.0


def test_build_holdings_cashflow_empty_for_no_positions() -> None:
    events = build_holdings_cashflow([], horizon_date=date.today() + timedelta(days=365), today=date.today())
    assert events == []
