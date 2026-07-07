"""Тесты `domain.trading.top_up.apply_top_up_distribution`."""

from __future__ import annotations

from datetime import date

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
from bond_monitor.domain.portfolio.planner import TopUpAllocation
from bond_monitor.domain.trading.top_up import (
    apply_top_up_distribution,
    cancel_top_up_batch,
    has_active_top_up_batch,
)


def _bond(isin: str = "RU000A001") -> BondRecord:
    bond = BondRecord(
        secid=isin[:6],
        isin=isin,
        name="Test Bond",
        maturity_date=date(2026, 12, 31),
        last_price=100.0,
        face_value=1000.0,
        lot_size=1,
        coupon_rate=10.0,
        coupon_period_days=180,
        volume_rub=1_000_000.0,
        liquidity_flag=True,
        credit_rating="ruAAA",
        risk_level=RiskLevel.LOW,
        ytm=12.0,
        ytm_net=10.0,
    )
    bond.accrued_interest = 0.0
    return bond


def _position(*, isin: str = "RU000A001", lots: int = 5) -> PortfolioPosition:
    return PortfolioPosition(
        isin=isin,
        secid="RU000A",
        name="Existing",
        lots=lots,
        lot_size=1,
        purchase_clean_price_pct=100.0,
        purchase_dirty_price_rub=1000.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2025, 1, 1),
        purchase_amount_rub=1000.0 * lots,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=date(2026, 12, 31),
        offer_date=None,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        figi="BBG_EXIST",
        actual_lots=lots,
    )


def _trading_portfolio() -> Portfolio:
    return Portfolio(
        name="T",
        initial_amount_rub=100_000.0,
        horizon_date=date(2026, 12, 31),
        risk_profile=RiskProfile.NORMAL,
        mode=PortfolioMode.TRADING,
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        trading_started_at="2025-01-01T00:00:00+00:00",
    )


def test_apply_bumps_existing_position_lots() -> None:
    portfolio = _trading_portfolio()
    portfolio.positions = [_position(lots=5)]
    bond = _bond()
    allocations = [
        TopUpAllocation(
            isin="RU000A001",
            figi="BBG_EXIST",
            name="Existing",
            lots=2,
            suggested_price_pct=100.5,
            estimated_amount_rub=2010.0,
            is_existing_position=True,
        )
    ]

    notes = apply_top_up_distribution(
        portfolio,
        allocations,
        distributed_amount_rub=2010.0,
        batch_id="batch-1",
        processed_at_iso="2025-06-15T12:00:00+00:00",
        universe_by_isin={bond.isin: bond},
        today=date(2025, 6, 15),
    )

    assert portfolio.positions[0].lots == 7
    assert portfolio.acknowledged_top_ups_rub == 2010.0
    assert portfolio.last_top_up_processed_at == "2025-06-15T12:00:00+00:00"
    assert len(portfolio.pending_operations) == 1
    assert portfolio.pending_operations[0].kind == "top_up_buy"
    assert portfolio.pending_operations[0].top_up_batch_id == "batch-1"
    assert notes


def test_apply_adds_new_position_for_new_isin() -> None:
    portfolio = _trading_portfolio()
    bond = _bond("RU000A002")
    allocations = [
        TopUpAllocation(
            isin="RU000A002",
            figi="BBG_NEW",
            name="New Bond",
            lots=3,
            suggested_price_pct=101.0,
            estimated_amount_rub=3030.0,
            is_existing_position=False,
        )
    ]

    apply_top_up_distribution(
        portfolio,
        allocations,
        distributed_amount_rub=3030.0,
        batch_id="batch-2",
        processed_at_iso="2025-06-15T12:00:00+00:00",
        universe_by_isin={bond.isin: bond},
        today=date(2025, 6, 15),
    )

    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].isin == "RU000A002"
    assert portfolio.positions[0].lots == 3
    assert portfolio.positions[0].figi == "BBG_NEW"


def test_has_active_top_up_batch() -> None:
    portfolio = _trading_portfolio()
    assert not has_active_top_up_batch(portfolio)
    portfolio.pending_operations = [
        PendingOperation(
            kind="top_up_buy",
            isin="RU000A001",
            name="X",
            lots=1,
            top_up_batch_id="batch-1",
        )
    ]
    assert has_active_top_up_batch(portfolio)


def test_cancel_top_up_batch_rolls_back() -> None:
    portfolio = _trading_portfolio()
    portfolio.positions = [_position(lots=5)]
    portfolio.last_top_up_processed_at = "2025-01-01T00:00:00+00:00"
    bond = _bond()
    apply_top_up_distribution(
        portfolio,
        [
            TopUpAllocation(
                isin="RU000A001",
                figi="BBG_EXIST",
                name="Existing",
                lots=2,
                suggested_price_pct=100.5,
                estimated_amount_rub=2010.0,
                is_existing_position=True,
            )
        ],
        distributed_amount_rub=2010.0,
        batch_id="batch-1",
        processed_at_iso="2025-06-15T12:00:00+00:00",
        universe_by_isin={bond.isin: bond},
        today=date(2025, 6, 15),
    )
    assert portfolio.positions[0].lots == 7

    cancel_top_up_batch(portfolio, "batch-1")

    assert portfolio.positions[0].lots == 5
    assert portfolio.acknowledged_top_ups_rub == 0.0
    assert portfolio.last_top_up_processed_at is not None
    assert portfolio.last_top_up_processed_at != "2025-01-01T00:00:00+00:00"
    assert not portfolio.pending_operations
    assert "batch-1" not in portfolio.top_up_batch_meta
