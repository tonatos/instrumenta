"""Тесты жизненного цикла позиций в TRADING."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, CouponType
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
    TradeRecord,
)
from bond_monitor.domain.portfolio.position_status import position_status
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.portfolio.reinvestment import reinvest_buy_stable_id
from bond_monitor.domain.trading.ids import stable_id
from bond_monitor.domain.trading.position_lifecycle import (
    apply_filled_reinvest_buys,
    close_matured_positions,
    ensure_reinvest_position,
    position_was_ever_held,
)
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    BondPosition,
)


def _bond(*, isin: str = "RU000A002", figi: str = "BBG_NEW") -> BondRecord:
    return BondRecord(
        secid="SEC2",
        isin=isin,
        name="OFZ 2",
        figi=figi,
        maturity_date=date(2028, 1, 1),
        coupon_type=CouponType.FIXED,
        last_price=95.0,
        face_value=1000.0,
        lot_size=1,
        accrued_interest=10.0,
    )


def _position(
    *,
    isin: str = "RU000A001",
    figi: str = "FIGI1",
    lots: int = 5,
    actual_lots: int | None = 5,
    maturity_date: date | None = date(2027, 6, 1),
    closed_at: date | None = None,
    source: PositionSourceType = PositionSourceType.INITIAL,
    put_offer_decision: PutOfferDecision = PutOfferDecision.PENDING,
    offer_date: date | None = None,
) -> PortfolioPosition:
    return PortfolioPosition(
        isin=isin,
        secid="SEC1",
        name="OFZ 1",
        lots=lots,
        lot_size=1,
        purchase_clean_price_pct=95.0,
        purchase_dirty_price_rub=960.0,
        purchase_aci_rub=10.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=960.0 * lots,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=maturity_date,
        offer_date=offer_date,
        coupon_period_days=182,
        source=source,
        put_offer_decision=put_offer_decision,
        figi=figi,
        actual_lots=actual_lots,
        closed_at=closed_at,
    )


def _portfolio(*, positions: list[PortfolioPosition] | None = None) -> Portfolio:
    p = Portfolio(
        name="Test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2028, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    p.mode = PortfolioMode.TRADING
    p.account_id = "acc-1"
    p.account_kind = AccountKind.SANDBOX
    p.positions = list(positions or [])
    return p


def _snapshot(*, bonds: dict[str, BondPosition] | None = None) -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions=bonds or {},
        other_instruments=[],
        fetched_at="2026-07-01T00:00:00+00:00",
    )


# ── position_status ──────────────────────────────────────────────────────────


def test_position_status_closed() -> None:
    pos = _position(closed_at=date(2026, 6, 1))
    assert position_status(pos, is_trading=True, today=date(2026, 7, 1)) == "closed"


def test_position_status_pending() -> None:
    pos = _position(lots=5, actual_lots=0)
    assert position_status(pos, is_trading=True, today=date(2026, 7, 1)) == "pending"


def test_position_status_active() -> None:
    pos = _position(lots=5, actual_lots=5)
    assert position_status(pos, is_trading=True, today=date(2026, 7, 1)) == "active"


def test_position_status_drift_extra_lots() -> None:
    pos = _position(lots=5, actual_lots=7)
    assert position_status(pos, is_trading=True, today=date(2026, 7, 1)) == "drift"


def test_position_status_simulation_always_active() -> None:
    pos = _position(lots=5, actual_lots=0)
    assert position_status(pos, is_trading=False, today=date(2026, 7, 1)) == "active"


# ── ensure_reinvest_position ─────────────────────────────────────────────────


def test_ensure_reinvest_position_creates_new() -> None:
    portfolio = _portfolio()
    bond = _bond()
    ensure_reinvest_position(
        portfolio,
        bond,
        lots=3,
        source=PositionSourceType.REINVEST_MATURITY,
        figi="BBG_NEW",
        today=date(2026, 7, 1),
        purchase_price_pct=95.0,
    )
    assert len(portfolio.positions) == 1
    pos = portfolio.positions[0]
    assert pos.isin == "RU000A002"
    assert pos.lots == 3
    assert pos.source == PositionSourceType.REINVEST_MATURITY
    assert pos.figi == "BBG_NEW"


def test_ensure_reinvest_position_bumps_existing_open() -> None:
    portfolio = _portfolio(
        positions=[
            _position(
                isin="RU000A002",
                figi="BBG_NEW",
                lots=2,
                actual_lots=2,
                source=PositionSourceType.REINVEST_MATURITY,
            )
        ]
    )
    bond = _bond()
    ensure_reinvest_position(
        portfolio,
        bond,
        lots=1,
        source=PositionSourceType.REINVEST_MATURITY,
        figi="BBG_NEW",
        today=date(2026, 7, 1),
        purchase_price_pct=95.0,
    )
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].lots == 3


# ── close_matured_positions ──────────────────────────────────────────────────


def test_close_matured_positions_archives_matured_bond() -> None:
    portfolio = _portfolio(
        positions=[_position(maturity_date=date(2026, 6, 1), actual_lots=0, lots=5)]
    )
    portfolio.trade_records.append(
        TradeRecord(
            request_uid="uid1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="FIGI1",
            direction="BUY",
            lots=5,
            status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=5,
        )
    )
    closed = close_matured_positions(portfolio, _snapshot(), today=date(2026, 7, 1))
    assert closed == 1
    assert portfolio.positions[0].closed_at == date(2026, 7, 1)


def test_close_matured_positions_skips_pending_initial_buy() -> None:
    portfolio = _portfolio(
        positions=[_position(maturity_date=date(2028, 1, 1), actual_lots=0, lots=5)]
    )
    closed = close_matured_positions(portfolio, _snapshot(), today=date(2026, 7, 1))
    assert closed == 0
    assert portfolio.positions[0].closed_at is None


def test_position_was_ever_held_from_trade_record() -> None:
    portfolio = _portfolio(positions=[_position(actual_lots=0)])
    assert position_was_ever_held(portfolio, portfolio.positions[0]) is False
    portfolio.trade_records.append(
        TradeRecord(
            request_uid="uid1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="FIGI1",
            direction="BUY",
            lots=5,
            status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=5,
        )
    )
    assert position_was_ever_held(portfolio, portfolio.positions[0]) is True


# ── apply_filled_reinvest_buys ───────────────────────────────────────────────


def test_apply_filled_reinvest_buys_creates_position_from_fill() -> None:
    portfolio = _portfolio()
    target_isin = "RU000A002"
    trigger = date(2026, 6, 15)
    portfolio.slots.append(
        ReinvestmentSlot(
            trigger_date=trigger,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=20_000.0,
            suggested_isin=target_isin,
            suggested_name="OFZ 2",
            source_position_isin="RU000A001",
        )
    )
    slot = portfolio.slots[0]
    op_id = reinvest_buy_stable_id(portfolio, slot)
    portfolio.trade_records.append(
        TradeRecord(
            request_uid="uid-reinv",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG_NEW",
            direction="BUY",
            lots=2,
            pending_op_id=op_id,
            status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=2,
            price_pct=95.0,
        )
    )
    bond = _bond(isin=target_isin)
    created = apply_filled_reinvest_buys(
        portfolio,
        {bond.isin: bond},
        today=date(2026, 7, 1),
    )
    assert created == 1
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].isin == target_isin
    assert portfolio.positions[0].source == PositionSourceType.REINVEST_MATURITY


def test_reinvest_buy_available_before_matured_position_closed() -> None:
    """Погашенная позиция (actual_lots=0) ещё даёт reinvest_buy до close_matured."""
    from bond_monitor.domain.portfolio.planner import build_plan
    from bond_monitor.domain.trading.pending_operations import compute_pending_operations
    from factories import make_account_snapshot, make_live_bond

    today = date(2026, 7, 5)
    maturing_isin = "RU000MAT01"
    replacement_isin = "RU000REPL1"
    maturing = make_live_bond(
        isin=maturing_isin,
        name="Maturing",
        maturity=date(2026, 7, 1),
        price=99.0,
    )
    maturing.figi = "FIGI_MAT"
    replacement = make_live_bond(
        isin=replacement_isin,
        name="Replacement",
        maturity=date(2027, 6, 1),
        price=100.0,
    )
    replacement.figi = "FIGI_REPL"

    portfolio = _portfolio(
        positions=[
            PortfolioPosition(
                isin=maturing_isin,
                secid="MAT01",
                name="Maturing",
                lots=5,
                lot_size=1,
                figi="FIGI_MAT",
                actual_lots=0,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_date=date(2026, 1, 1),
                purchase_amount_rub=4_950.0,
                coupon_rate=12.0,
                face_value=1000.0,
                maturity_date=date(2026, 7, 1),
                offer_date=None,
                coupon_period_days=182,
                source=PositionSourceType.INITIAL,
            )
        ]
    )
    portfolio.trade_records.append(
        TradeRecord(
            request_uid="uid-buy",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="FIGI_MAT",
            direction="BUY",
            lots=5,
            status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=5,
        )
    )
    snapshot = make_account_snapshot(money_rub=5_000.0, fetched_at="2026-07-05T12:00:00+00:00")

    plan = build_plan(
        portfolio,
        [maturing, replacement],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=5_000.0,
        assume_best_put_outcome=False,
    )
    pending = compute_pending_operations(
        portfolio,
        snapshot,
        today,
        universe=[maturing, replacement],
        resolved_slots=plan.resolved_slots,
    )
    reinvest_ops = [op for op in pending if op.kind == "reinvest_buy"]
    assert reinvest_ops, "должен появиться reinvest_buy до архивации позиции"

    closed = close_matured_positions(portfolio, snapshot, today=today)
    assert closed == 1
    assert portfolio.positions[0].closed_at == today
