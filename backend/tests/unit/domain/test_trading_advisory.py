"""Unit tests for stateless trading advisory."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bond_monitor.domain.portfolio.models import PortfolioPosition, PositionSourceType, RiskProfile
from bond_monitor.domain.portfolio.risk_monitor import RiskSnapshot
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.advisory import (
    advise,
    build_holdings,
    build_holdings_cashflow,
    effective_trading_positions,
    holding_isins_from_snapshot,
    validate_attach_soft,
)
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


def test_holding_isins_from_snapshot_requires_universe_for_figi_mapping() -> None:
    bond = make_bond(isin="RU000A1", figi="FIGI-HOLD")
    snapshot = make_account_snapshot(
        50_000.0,
        bond_positions={"FIGI-HOLD": _bond_position()},
    )
    assert holding_isins_from_snapshot(snapshot, []) == set()
    assert holding_isins_from_snapshot(snapshot, [bond]) == {"RU000A1"}


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
    from bond_monitor.domain.portfolio.plan_models import MIN_AUTO_POSITIONS

    universe = [
        make_bond(
            isin=f"RU000A{i:03d}",
            name=f"Bond {i}",
            figi=f"FIGI-{i}",
            price=100.0,
            ytm=18.0 + i,
            score=80.0 + i,
            maturity=date.today() + timedelta(days=200 + i),
        )
        for i in range(8)
    ]
    portfolio = make_portfolio(
        initial_amount_rub=100_000.0,
        horizon_date=date.today() + timedelta(days=400),
        risk_profile=RiskProfile.NORMAL,
        account_kind="sandbox",
        api_trade_only=False,
    )
    snapshot = make_account_snapshot(80_000.0)
    advice = advise(
        portfolio,
        snapshot,
        active_orders=[],
        operations=[],
        universe=universe,
        key_rate=16.0,
        tax_rate=0.13,
        today=date.today(),
    )
    buy_suggestions = [s for s in advice.suggestions if s.kind == "buy"]
    assert len(buy_suggestions) >= MIN_AUTO_POSITIONS
    assert len({s.isin for s in buy_suggestions}) == len(buy_suggestions)
    assert all(s.lots >= 1 for s in buy_suggestions)
    assert all(s.suggested_price_pct is not None for s in buy_suggestions)
    assert all(s.market_price_pct is not None for s in buy_suggestions)


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


def test_advise_put_offer_watch_when_window_unknown() -> None:
    offer_date = date(2026, 8, 7)
    bond = make_bond(
        isin="RU000A109874",
        name="СамолетP15",
        figi="FIGI-SAM",
        maturity=date(2027, 7, 30),
    )
    bond.offer_date = offer_date
    bond.offer_price_pct = 100.0
    portfolio = make_portfolio(horizon_date=date(2028, 1, 1))
    portfolio.positions = [
        PortfolioPosition(
            isin=bond.isin,
            secid=bond.secid,
            name=bond.name,
            lots=10,
            lot_size=1,
            purchase_clean_price_pct=99.0,
            purchase_dirty_price_rub=990.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 7, 8),
            purchase_amount_rub=99_000.0,
            coupon_rate=12.0,
            face_value=1000.0,
            maturity_date=date(2027, 7, 30),
            offer_date=offer_date,
            offer_price_pct=100.0,
            coupon_period_days=91,
            source=PositionSourceType.ADOPTED,
        )
    ]
    snapshot = make_account_snapshot(
        5_000.0,
        bond_positions={"FIGI-SAM": _bond_position(figi="FIGI-SAM", lots=10)},
    )
    advice = advise(
        portfolio,
        snapshot,
        active_orders=[],
        operations=[],
        universe=[bond],
        key_rate=16.0,
        tax_rate=0.13,
        today=date(2026, 7, 10),
    )
    reminders = [s for s in advice.suggestions if s.kind == "put_offer_reminder"]
    watches = [s for s in advice.suggestions if s.kind == "put_offer_watch"]
    assert not reminders
    assert len(watches) == 1
    assert watches[0].offer_window_status == "unknown"
    assert "не объявлено" in watches[0].reason


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


def test_effective_trading_positions_adopts_broker_holdings_with_average_price() -> None:
    bond = make_bond(isin="RU000A1", figi="FIGI-HOLD", name="Hold Bond")
    snapshot = make_account_snapshot(
        50_000.0,
        bond_positions={"FIGI-HOLD": _bond_position(figi="FIGI-HOLD", lots=3, quantity=3)},
    )
    portfolio = make_portfolio()
    positions = effective_trading_positions(
        portfolio,
        snapshot,
        [bond],
        purchase_date=date.today(),
    )
    assert len(positions) == 1
    assert positions[0].source == PositionSourceType.ADOPTED
    assert positions[0].lots == 3
    assert positions[0].purchase_clean_price_pct == pytest.approx(95.0)


def test_effective_trading_positions_keeps_pending_plan_not_on_account() -> None:
    bond = make_bond(isin="RU000ON", figi="FIGI-ON")
    pending_bond = make_bond(isin="RU000PEND", figi="FIGI-PEND", name="Pending")
    from bond_monitor.domain.portfolio.position_factory import position_from_bond

    portfolio = make_portfolio()
    portfolio.positions = [
        position_from_bond(
            pending_bond,
            lots=2,
            purchase_date=date.today(),
            source=PositionSourceType.INITIAL,
        )
    ]
    snapshot = make_account_snapshot(
        10_000.0,
        bond_positions={"FIGI-ON": _bond_position(figi="FIGI-ON", lots=1, quantity=1)},
    )
    positions = effective_trading_positions(
        portfolio,
        snapshot,
        [bond, pending_bond],
        purchase_date=date.today(),
    )
    assert len(positions) == 2
    adopted = [p for p in positions if p.isin == "RU000ON"]
    pending = [p for p in positions if p.isin == "RU000PEND"]
    assert len(adopted) == 1
    assert adopted[0].source == PositionSourceType.ADOPTED
    assert len(pending) == 1
    assert pending[0].source == PositionSourceType.INITIAL


def test_validate_attach_soft_counts_deployed_bonds_in_effective_initial() -> None:
    bond = make_bond(isin="RU000A1", figi="FIGI-HOLD")
    snapshot = make_account_snapshot(
        20_000.0,
        bond_positions={"FIGI-HOLD": _bond_position(figi="FIGI-HOLD", lots=2, quantity=2)},
    )
    portfolio = make_portfolio(initial_amount_rub=100_000.0)
    validation = validate_attach_soft(snapshot, portfolio, [bond])
    assert validation.effective_initial_amount_rub > 20_000.0


def test_validate_attach_soft_handles_missing_price_per_lot() -> None:
    bond = make_bond(isin="RU000A1", figi="FIGI-HOLD", last_price=None)
    snapshot = make_account_snapshot(
        20_000.0,
        bond_positions={
            "FIGI-HOLD": BrokerBondPosition(
                figi="FIGI-HOLD",
                instrument_uid="uid-hold",
                ticker="SU26238",
                quantity=2,
                lots=2,
                blocked=0,
                current_price_pct=None,
                current_nkd_rub=None,
                average_price_pct=None,
            )
        },
    )
    portfolio = make_portfolio(initial_amount_rub=100_000.0)
    validation = validate_attach_soft(snapshot, portfolio, [bond])
    assert validation.can_attach is True
    assert validation.effective_initial_amount_rub == 100_000.0


def test_advise_emits_risk_sell_on_default_escalation() -> None:
    bond = make_bond(isin="RU000A1", name="Risk Bond", figi="FIGI-HOLD", ytm=17.5)
    bond.has_default = True
    portfolio = make_portfolio(
        horizon_date=date.today() + timedelta(days=365),
        risk_profile=RiskProfile.NORMAL,
    )
    portfolio.risk_baselines = {
        "RU000A1": RiskSnapshot(has_default=False, credit_rating=bond.credit_rating),
    }
    snapshot = make_account_snapshot(
        10_000.0,
        bond_positions={"FIGI-HOLD": _bond_position()},
    )
    advice = advise(
        portfolio,
        snapshot,
        [],
        [],
        [bond],
        key_rate=14.5,
        tax_rate=0.13,
    )
    sells = [s for s in advice.suggestions if s.kind == "sell"]
    assert len(sells) == 1
    assert sells[0].isin == "RU000A1"
    assert sells[0].risk_acknowledgeable is True
    assert sells[0].urgency == "critical"


def test_advise_skips_risk_sell_when_baseline_matches_current() -> None:
    bond = make_bond(isin="RU000A1", name="Risk Bond", figi="FIGI-HOLD", ytm=17.5)
    bond.has_default = True
    portfolio = make_portfolio(
        horizon_date=date.today() + timedelta(days=365),
        risk_profile=RiskProfile.NORMAL,
    )
    portfolio.risk_baselines = {
        "RU000A1": RiskSnapshot(has_default=True, credit_rating=bond.credit_rating),
    }
    snapshot = make_account_snapshot(
        10_000.0,
        bond_positions={"FIGI-HOLD": _bond_position()},
    )
    advice = advise(
        portfolio,
        snapshot,
        [],
        [],
        [bond],
        key_rate=14.5,
        tax_rate=0.13,
    )
    assert [s for s in advice.suggestions if s.kind == "sell"] == []
