"""Tests for order request UID after cancel/reject."""

from __future__ import annotations

from datetime import date

from bond_monitor.application.trading.trading_service import _order_request_uid
from bond_monitor.domain.portfolio.models import (
    AccountKind,
    Portfolio,
    RiskProfile,
    TradeRecord,
)


def test_order_request_uid_uses_new_salt_after_cancel() -> None:
    portfolio = Portfolio(
        name="Retry",
        initial_amount_rub=100_000,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    fresh = _order_request_uid(
        portfolio,
        account_id="acc-1",
        figi="BBG123",
        direction="BUY",
        lots=1,
        pending_op_id="pending-1",
    )
    portfolio.trade_records.append(
        TradeRecord(
            request_uid=fresh,
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG123",
            direction="BUY",
            lots=1,
            pending_op_id="pending-1",
            order_id="order-old",
            status="EXECUTION_REPORT_STATUS_CANCELLED",
        )
    )
    retry = _order_request_uid(
        portfolio,
        account_id="acc-1",
        figi="BBG123",
        direction="BUY",
        lots=1,
        pending_op_id="pending-1",
    )
    assert retry != fresh
