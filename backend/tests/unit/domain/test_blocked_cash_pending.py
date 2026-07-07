"""Тесты blocked/available кэша в очереди покупок."""

from __future__ import annotations

from datetime import date

import pytest

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
    PendingOperation,
    TradeRecord,
)
from bond_monitor.domain.trading.pending_operations import (
    compute_pending_operations,
    sweep_unfunded_top_up_buys,
)
from bond_monitor.domain.trading.ports import BrokerSnapshot
from bond_monitor.domain.shared.money import PriceUnitPct, Rub


def _bond(isin: str = "RU000SAMO", *, price: float = 100.0, figi: str = "FIGI_SAMO") -> BondRecord:
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
    bond.figi = figi
    bond.accrued_interest = 0.0
    bond.api_trade_available_flag = True
    return bond


def _position(
    *,
    isin: str = "RU000SAMO",
    lots: int = 10,
    actual_lots: int = 0,
    figi: str = "FIGI_SAMO",
) -> PortfolioPosition:
    return PortfolioPosition(
        isin=isin,
        secid="SAMO13",
        name="СамолетP13",
        lots=lots,
        lot_size=1,
        purchase_clean_price_pct=100.0,
        purchase_dirty_price_rub=1000.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=1000.0 * lots,
        coupon_rate=12.0,
        face_value=1000.0,
        maturity_date=date(2027, 6, 1),
        offer_date=None,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        figi=figi,
        actual_lots=actual_lots,
    )


def _trading_portfolio(*, positions: list[PortfolioPosition] | None = None) -> Portfolio:
    p = Portfolio(
        name="Blocked cash",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.NORMAL,
        mode=PortfolioMode.TRADING,
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        trading_started_at="2026-01-01T00:00:00+00:00",
    )
    p.positions = positions or [_position()]
    return p


def _snapshot(*, money: float, blocked: float = 0.0) -> BrokerSnapshot:
    return BrokerSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money),
        blocked_money_rub=Rub(blocked),
        bond_positions={},
        other_instruments=[],
        fetched_at="2026-07-08T00:00:00+00:00",
    )


def test_broker_snapshot_available_money_rub() -> None:
    snap = _snapshot(money=50_000.0, blocked=45_641.5)
    assert float(snap.available_money_rub) == pytest.approx(4358.5)


def test_sweep_unfunded_top_up_buys_removes_ops_without_cash() -> None:
    portfolio = _trading_portfolio()
    bond = _bond()
    portfolio.pending_operations = [
        PendingOperation(
            id="top-1",
            kind="top_up_buy",
            isin=bond.isin,
            name=bond.name,
            lots=30,
            figi=bond.figi,
            suggested_price_pct=100.0,
            estimated_amount_rub=30_000.0,
            top_up_batch_id="batch-1",
        )
    ]
    removed = sweep_unfunded_top_up_buys(portfolio, 2_000.0, {bond.isin: bond})
    assert removed == 1
    assert portfolio.pending_operations == []


def test_sweep_unfunded_top_up_buys_keeps_ops_with_active_order() -> None:
    portfolio = _trading_portfolio()
    bond = _bond()
    pending_op = PendingOperation(
        id="top-1",
        kind="top_up_buy",
        isin=bond.isin,
        name=bond.name,
        lots=30,
        figi=bond.figi,
        suggested_price_pct=100.0,
        estimated_amount_rub=30_000.0,
        top_up_batch_id="batch-1",
    )
    portfolio.pending_operations = [pending_op]
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi=bond.figi,
            direction="BUY",
            lots=30,
            pending_op_id=pending_op.id,
            order_id="order-1",
            status="EXECUTION_REPORT_STATUS_NEW",
            total_order_amount_rub=30_000.0,
        )
    ]
    removed = sweep_unfunded_top_up_buys(portfolio, 0.0, {bond.isin: bond})
    assert removed == 0
    assert len(portfolio.pending_operations) == 1


def test_compute_pending_blocks_buys_above_available_cash() -> None:
    portfolio = _trading_portfolio(positions=[_position(lots=10, actual_lots=0)])
    bond = _bond()
    snapshot = _snapshot(money=50_000.0, blocked=48_000.0)

    ops = compute_pending_operations(
        portfolio,
        snapshot,
        date(2026, 7, 8),
        universe=[bond],
    )
    buys = [op for op in ops if op.kind == "initial_buy"]
    assert len(buys) == 1
    assert buys[0].status == "blocked"
    assert buys[0].block_reason is not None
    assert "Недостаточно свободных" in buys[0].block_reason


def test_compute_pending_funds_buys_within_available_cash() -> None:
    portfolio = _trading_portfolio(positions=[_position(lots=2, actual_lots=0)])
    bond = _bond()
    snapshot = _snapshot(money=5_000.0, blocked=0.0)

    ops = compute_pending_operations(
        portfolio,
        snapshot,
        date(2026, 7, 8),
        universe=[bond],
    )
    buys = [op for op in ops if op.kind == "initial_buy"]
    assert len(buys) == 1
    assert buys[0].status == "action_required"
