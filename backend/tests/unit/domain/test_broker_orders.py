"""Tests for importing active broker orders into portfolio state."""

from __future__ import annotations

from datetime import date

import pytest

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    RiskProfile,
)
from bond_monitor.domain.trading.broker_orders import reconcile_active_broker_orders
from bond_monitor.domain.trading.models import AccountKind, TradeRecord
from bond_monitor.domain.trading.pending_operations import compute_pending_operations
from bond_monitor.domain.trading.ports import BrokerActiveOrder, BrokerSnapshot
from bond_monitor.domain.shared.money import Rub


def _trading_portfolio() -> Portfolio:
    p = Portfolio(
        name="Trading test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    p.mode = PortfolioMode.TRADING
    p.account_id = "acc-1"
    p.account_kind = AccountKind.SANDBOX
    p.trading_started_at = "2025-01-01T00:00:00+00:00"
    return p


def _position(*, figi: str = "FIGI1", actual_lots: int = 3) -> PortfolioPosition:
    return PortfolioPosition(
        isin="RU000TEST1",
        secid="TEST1",
        name="Тестовая облигация",
        lots=3,
        lot_size=1,
        purchase_clean_price_pct=100.0,
        purchase_dirty_price_rub=1000.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2025, 1, 1),
        purchase_amount_rub=3000.0,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=date(2027, 6, 1),
        offer_date=None,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        put_offer_decision=PutOfferDecision.PENDING,
        figi=figi,
        actual_lots=actual_lots,
    )


def _sell_order(**kwargs) -> BrokerActiveOrder:
    defaults = {
        "order_id": "broker-sell-1",
        "request_uid": "uid-sell-1",
        "figi": "FIGI1",
        "direction": "SELL",
        "lots_requested": 2,
        "lots_executed": 0,
        "status": "EXECUTION_REPORT_STATUS_NEW",
        "price_pct": 90.6,
        "total_order_amount_rub": 1980.0,
        "initial_commission_rub": 5.0,
    }
    defaults.update(kwargs)
    return BrokerActiveOrder(**defaults)


def _empty_snapshot() -> BrokerSnapshot:
    return BrokerSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at="2025-06-01T12:00:00+00:00",
    )


def test_imports_orphan_sell_order_and_manual_sell_pending() -> None:
    portfolio = _trading_portfolio()
    portfolio.positions = [_position()]

    imported = reconcile_active_broker_orders(
        portfolio,
        [_sell_order()],
        universe_by_isin={},
    )

    assert imported == 1
    assert len(portfolio.trade_records) == 1
    tr = portfolio.trade_records[0]
    assert tr.order_id == "broker-sell-1"
    assert tr.direction == "SELL"
    assert tr.pending_op_id is not None

    pending = compute_pending_operations(portfolio, _empty_snapshot(), date(2025, 6, 1))
    sells = [op for op in pending if op.kind == "manual_sell"]
    assert len(sells) == 1
    assert sells[0].status == "in_progress"
    assert sells[0].active_order_id == "broker-sell-1"
    assert sells[0].lots == 2


def test_links_existing_trade_record_without_pending_op() -> None:
    portfolio = _trading_portfolio()
    portfolio.positions = [_position()]
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-sell-1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="FIGI1",
            direction="SELL",
            lots=2,
            order_id="broker-sell-1",
            price_pct=99.0,
            status="EXECUTION_REPORT_STATUS_NEW",
        )
    ]

    imported = reconcile_active_broker_orders(
        portfolio,
        [_sell_order()],
        universe_by_isin={},
    )

    assert imported == 0
    assert len(portfolio.pending_operations) == 1
    assert portfolio.pending_operations[0].kind == "manual_sell"
    assert portfolio.trade_records[0].pending_op_id == portfolio.pending_operations[0].id
    assert portfolio.trade_records[0].price_pct == pytest.approx(90.6)
    assert portfolio.pending_operations[0].suggested_price_pct == pytest.approx(90.6)


def test_reconcile_updates_stale_ruble_price_as_pct() -> None:
    portfolio = _trading_portfolio()
    portfolio.positions = [_position()]
    portfolio.pending_operations = []
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-sell-1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="FIGI1",
            direction="SELL",
            lots=36,
            order_id="broker-sell-1",
            price_pct=906.0,
            status="EXECUTION_REPORT_STATUS_NEW",
        )
    ]

    reconcile_active_broker_orders(
        portfolio,
        [_sell_order(lots_requested=36, price_pct=90.6)],
        universe_by_isin={},
    )

    assert portfolio.trade_records[0].price_pct == pytest.approx(90.6)


def test_imports_buy_order_without_manual_sell() -> None:
    portfolio = _trading_portfolio()
    portfolio.positions = [_position(actual_lots=0)]

    imported = reconcile_active_broker_orders(
        portfolio,
        [
            _sell_order(
                order_id="broker-buy-1",
                request_uid="uid-buy-1",
                direction="BUY",
                figi="FIGI1",
            )
        ],
        universe_by_isin={},
    )

    assert imported == 1
    assert not portfolio.pending_operations
    assert portfolio.trade_records[0].direction == "BUY"
