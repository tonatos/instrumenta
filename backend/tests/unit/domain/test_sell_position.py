"""Тесты валидации прямой продажи позиции в песочнице."""

from __future__ import annotations

from datetime import date

import pytest

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.trading.models import AccountKind, PendingOperation, TradeRecord
from bond_monitor.domain.trading.sell_position import (
    SANDBOX_ONLY_MSG,
    dismiss_queued_manual_sell,
    dismiss_queued_pending,
    find_sellable_position,
    queue_manual_sell,
    validate_sell_request,
)


def _trading_portfolio(*, kind: AccountKind = AccountKind.SANDBOX) -> Portfolio:
    p = Portfolio(
        name="Trading test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    p.mode = PortfolioMode.TRADING
    p.account_id = "acc-1"
    p.account_kind = kind
    return p


def _position(
    *,
    isin: str = "RU000A1",
    lots: int = 5,
    actual_lots: int = 3,
    figi: str = "BBG1",
    closed: bool = False,
) -> PortfolioPosition:
    pos = PortfolioPosition(
        isin=isin,
        secid="TST",
        name="Test bond",
        lots=lots,
        lot_size=10,
        purchase_clean_price_pct=100.0,
        purchase_dirty_price_rub=1000.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2025, 1, 1),
        purchase_amount_rub=10000.0,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=date(2027, 1, 1),
        offer_date=None,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        figi=figi,
        actual_lots=actual_lots,
    )
    if closed:
        pos.closed_at = date(2026, 1, 1)
    return pos


def test_find_sellable_position_rejects_production() -> None:
    p = _trading_portfolio(kind=AccountKind.PRODUCTION)
    p.positions = [_position()]
    with pytest.raises(ValueError, match=SANDBOX_ONLY_MSG):
        find_sellable_position(p, "RU000A1")


def test_find_sellable_position_rejects_closed() -> None:
    p = _trading_portfolio()
    p.positions = [_position(closed=True)]
    with pytest.raises(ValueError, match="закрытую"):
        find_sellable_position(p, "RU000A1")


def test_find_sellable_position_rejects_missing() -> None:
    p = _trading_portfolio()
    with pytest.raises(ValueError, match="не найдена"):
        find_sellable_position(p, "RU000MISSING")


def test_validate_sell_request_rejects_zero_actual_lots() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=0)
    with pytest.raises(ValueError, match="нет лотов"):
        validate_sell_request(p, pos, lots=1)


def test_validate_sell_request_rejects_too_many_lots() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=2)
    with pytest.raises(ValueError, match="только 2"):
        validate_sell_request(p, pos, lots=3)


def test_validate_sell_request_rejects_active_sell_order() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    p.trade_records = [
        TradeRecord(
            request_uid="u1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="SELL",
            lots=1,
            status="EXECUTION_REPORT_STATUS_NEW",
        )
    ]
    with pytest.raises(ValueError, match="активная заявка"):
        validate_sell_request(p, pos, lots=1)


def test_validate_sell_request_returns_available_lots() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    assert validate_sell_request(p, pos, lots=2) == 3


def test_validate_sell_request_allows_after_filled_sell() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    p.trade_records = [
        TradeRecord(
            request_uid="u1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="SELL",
            lots=1,
            status="EXECUTION_REPORT_STATUS_FILL",
        )
    ]
    assert validate_sell_request(p, pos, lots=1) == 3


def test_queue_manual_sell_creates_pending_operation() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    p.positions = [pos]

    op = queue_manual_sell(p, pos, lots=2, price_pct=99.5)

    assert op.kind == "manual_sell"
    assert op.lots == 2
    assert op.suggested_price_pct == 99.5
    assert len(p.pending_operations) == 1


def test_queue_manual_sell_replaces_existing_for_isin() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    p.positions = [pos]
    first = queue_manual_sell(p, pos, lots=1, price_pct=100.0)
    second = queue_manual_sell(p, pos, lots=2, price_pct=99.0)

    assert first.id == second.id
    assert len(p.pending_operations) == 1
    assert p.pending_operations[0].lots == 2
    assert p.pending_operations[0].suggested_price_pct == 99.0


def test_dismiss_queued_manual_sell_removes_from_queue() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    p.positions = [pos]
    op = queue_manual_sell(p, pos, lots=2, price_pct=99.0)

    dismiss_queued_manual_sell(p, op.id)

    assert p.pending_operations == []


def test_dismiss_rejects_when_order_in_progress() -> None:
    p = _trading_portfolio()
    pos = _position(actual_lots=3)
    p.positions = [pos]
    op = queue_manual_sell(p, pos, lots=2, price_pct=99.0)
    p.trade_records = [
        TradeRecord(
            request_uid="u1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="SELL",
            lots=2,
            pending_op_id=op.id,
            status="EXECUTION_REPORT_STATUS_NEW",
        )
    ]

    with pytest.raises(ValueError, match="уже на бирже"):
        dismiss_queued_manual_sell(p, op.id)


def test_dismiss_queued_top_up_buy_removes_from_queue() -> None:
    p = _trading_portfolio()
    op = PendingOperation(
        id="top-up-1",
        kind="top_up_buy",
        isin="RU000A1",
        name="Test",
        lots=5,
        top_up_batch_id="batch-1",
    )
    p.pending_operations = [op]

    dismiss_queued_pending(p, op.id)

    assert p.pending_operations == []


def test_dismiss_top_up_buy_rejects_when_order_on_exchange() -> None:
    p = _trading_portfolio()
    op = PendingOperation(
        id="top-up-2",
        kind="top_up_buy",
        isin="RU000A1",
        name="Test",
        lots=5,
        figi="BBG1",
        top_up_batch_id="batch-1",
    )
    p.pending_operations = [op]
    p.trade_records = [
        TradeRecord(
            request_uid="u1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="BUY",
            lots=5,
            pending_op_id=op.id,
            status="EXECUTION_REPORT_STATUS_NEW",
        )
    ]

    with pytest.raises(ValueError, match="уже на бирже"):
        dismiss_queued_pending(p, op.id)
