"""
Тесты `core.pending_operations.compute_pending_operations`.

Проверяем генерацию initial_buy / put_offer_submit и дедупликацию
через TradeRecord.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    AccountKind,
    PendingOperation,
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
    TradeRecord,
)
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.pending_operations import (
    api_trade_position_warnings,
    compute_pending_operations,
    sweep_completed_pending,
    sweep_non_api_tradable_pending,
)
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot, BondPosition


def _trading_portfolio() -> Portfolio:
    p = Portfolio(
        name="Trading test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    p.mode = PortfolioMode.TRADING
    p.api_trade_only = False
    p.account_id = "acc-1"
    p.account_kind = AccountKind.SANDBOX
    p.trading_started_at = "2025-01-01T00:00:00+00:00"
    return p


def _position(
    isin: str = "RU000A1",
    lots: int = 5,
    actual_lots: int = 0,
    figi: str = "BBG1",
    offer_date: date | None = None,
    offer_submission_end: date | None = None,
    decision: PutOfferDecision = PutOfferDecision.PENDING,
) -> PortfolioPosition:
    return PortfolioPosition(
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
        offer_date=offer_date,
        offer_submission_end=offer_submission_end,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        figi=figi,
        actual_lots=actual_lots,
        put_offer_decision=decision,
    )


def _empty_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def test_simulation_returns_empty() -> None:
    """В режиме симуляции pending operations не имеют смысла → []."""
    p = Portfolio(
        name="Sim",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    assert compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1)) == []


def test_initial_buy_generated_for_unfilled_position() -> None:
    """Позиция с `actual_lots < lots` → одна `initial_buy`."""
    p = _trading_portfolio()
    p.positions = [_position(lots=5, actual_lots=0)]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert len(pending) == 1
    assert pending[0].kind == "initial_buy"
    assert pending[0].lots == 5


def test_initial_buy_uses_production_buy_limit_buffer() -> None:
    """На боевом контуре лимит ≈ рынок +0.2%."""
    p = _trading_portfolio()
    p.account_kind = AccountKind.PRODUCTION
    p.positions = [_position(lots=1, actual_lots=0)]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert pending[0].suggested_price_pct == pytest.approx(100.2)
    assert "рынок +0.2%" in pending[0].reason


def test_initial_buy_remaining_after_partial_fill() -> None:
    """`actual_lots=2 lots=5` → pending на оставшиеся 3."""
    p = _trading_portfolio()
    p.positions = [_position(lots=5, actual_lots=2)]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert len(pending) == 1
    assert pending[0].lots == 3


def _bond(
    isin: str,
    *,
    api_trade_available: bool | None = True,
    figi: str = "BBG1",
) -> BondRecord:
    return BondRecord(
        secid=isin[:6],
        isin=isin,
        figi=figi,
        name="Test bond",
        maturity_date=date(2027, 1, 1),
        effective_date=date(2027, 1, 1),
        coupon_rate=10.0,
        coupon_period_days=180,
        face_value=1000.0,
        risk_level=RiskLevel.LOW,
        api_trade_available_flag=api_trade_available,
    )


def test_initial_buy_skipped_when_api_trade_only_and_not_tradable() -> None:
    """При api_trade_only не генерируем BUY для бумаг без API-торговли."""
    p = _trading_portfolio()
    p.api_trade_only = True
    p.positions = [_position(isin="RU_BAD", lots=5, actual_lots=0)]
    universe = [_bond("RU_BAD", api_trade_available=False)]
    pending = compute_pending_operations(
        p, _empty_snapshot(), date(2025, 6, 1), universe=universe
    )
    assert not pending


def test_initial_buy_generated_when_api_trade_only_and_tradable() -> None:
    p = _trading_portfolio()
    p.api_trade_only = True
    p.positions = [_position(isin="RU_OK", lots=3, actual_lots=0)]
    universe = [_bond("RU_OK", api_trade_available=True)]
    pending = compute_pending_operations(
        p, _empty_snapshot(), date(2025, 6, 1), universe=universe
    )
    assert len(pending) == 1
    assert pending[0].kind == "initial_buy"


def test_persisted_top_up_buy_filtered_when_not_api_tradable() -> None:
    """Сохранённый top_up_buy для не-API бумаги не попадает в очередь."""
    p = _trading_portfolio()
    p.api_trade_only = True
    p.positions = [_position(lots=5, actual_lots=5)]
    p.pending_operations = [
        PendingOperation(
            kind="top_up_buy",
            isin="RU_BAD",
            name="Blocked bond",
            lots=2,
            figi="BBG_BAD",
            top_up_batch_id="batch-1",
        )
    ]
    universe = [_bond("RU_BAD", api_trade_available=False, figi="BBG_BAD")]
    pending = compute_pending_operations(
        p, _empty_snapshot(), date(2025, 6, 1), universe=universe
    )
    assert not any(op.kind == "top_up_buy" for op in pending)


def test_sweep_non_api_tradable_pending_removes_stored_ops() -> None:
    p = _trading_portfolio()
    p.api_trade_only = True
    p.pending_operations = [
        PendingOperation(kind="top_up_buy", isin="RU_BAD", name="X", lots=1, figi="F1"),
        PendingOperation(kind="manual_sell", isin="RU_OK", name="Y", lots=1, figi="F2"),
    ]
    universe = {
        "RU_BAD": _bond("RU_BAD", api_trade_available=False),
        "RU_OK": _bond("RU_OK", api_trade_available=True),
    }
    removed = sweep_non_api_tradable_pending(p, universe)
    assert removed == 1
    assert len(p.pending_operations) == 1
    assert p.pending_operations[0].isin == "RU_OK"


def test_api_trade_position_warnings_lists_non_tradable_positions() -> None:
    p = _trading_portfolio()
    p.api_trade_only = True
    p.positions = [
        _position(isin="RU_BAD", lots=1),
        _position(isin="RU_OK", lots=1),
    ]
    universe = {
        "RU_BAD": _bond("RU_BAD", api_trade_available=False),
        "RU_OK": _bond("RU_OK", api_trade_available=True),
    }
    warnings = api_trade_position_warnings(p, universe)
    assert len(warnings) == 1
    assert "RU_BAD" in warnings[0]


def test_initial_buy_uses_universe_figi_over_stale_position_figi() -> None:
    """Enriched FIGI из universe приоритетнее устаревшего TCSM в позиции."""
    p = _trading_portfolio()
    p.api_trade_only = True
    pos = _position(isin="RU_OK", lots=3, actual_lots=0, figi="TCSM_STALE")
    p.positions = [pos]
    universe = [_bond("RU_OK", api_trade_available=True, figi="BBG_OK")]
    pending = compute_pending_operations(
        p, _empty_snapshot(), date(2025, 6, 1), universe=universe
    )
    assert len(pending) == 1
    assert pending[0].figi == "BBG_OK"


def test_initial_buy_skipped_when_position_fully_on_account() -> None:
    """Если факт на счёте догнал план — pending не нужен."""
    p = _trading_portfolio()
    p.positions = [_position(lots=5, actual_lots=5, figi="BBG1")]
    p.trade_records = [
        TradeRecord(
            request_uid="uid1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="BUY",
            lots=5,
            status="EXECUTION_REPORT_STATUS_FILL",
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert not pending


def test_initial_buy_skips_lots_covered_by_top_up_buy() -> None:
    """`top_up_buy` pending покрывает часть gap — initial_buy не дублирует."""
    p = _trading_portfolio()
    p.positions = [_position(isin="RU000A1", lots=7, actual_lots=5)]
    p.pending_operations = [
        PendingOperation(
            kind="top_up_buy",
            isin="RU000A1",
            name="Bond",
            lots=2,
            figi="BBG1",
            top_up_batch_id="batch-1",
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert not any(op.kind == "initial_buy" for op in pending)
    assert any(op.kind == "top_up_buy" for op in pending)


def test_put_offer_submit_generated_in_window() -> None:
    """Позиция с PENDING оферты в ближайшем окне → put_offer_submit."""
    p = _trading_portfolio()
    today = date(2025, 6, 1)
    p.positions = [
        _position(
            lots=5,
            actual_lots=5,
            offer_date=date(2025, 6, 20),  # 19 дней
            decision=PutOfferDecision.PENDING,
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), today)
    assert any(op.kind == "put_offer_submit" for op in pending)


def test_put_offer_submit_urgent_within_two_days_of_submission_deadline() -> None:
    """За 2 дня до срока подачи — критичное напоминание предъявить бумаги."""
    p = _trading_portfolio()
    today = date(2025, 6, 8)
    p.positions = [
        _position(
            lots=5,
            actual_lots=5,
            offer_date=date(2025, 6, 20),
            offer_submission_end=date(2025, 6, 10),
            decision=PutOfferDecision.PENDING,
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), today)
    put_ops = [op for op in pending if op.kind == "put_offer_submit"]
    assert len(put_ops) == 1
    op = put_ops[0]
    assert op.urgency == "critical"
    assert op.status == "action_required"
    assert "предъявите бумаги" in op.reason.lower()


def test_put_offer_submit_soon_between_three_and_seven_days() -> None:
    """3–7 дней до дедлайна — повышенная срочность без критического статуса."""
    p = _trading_portfolio()
    today = date(2025, 6, 1)
    p.positions = [
        _position(
            lots=5,
            actual_lots=5,
            offer_date=date(2025, 6, 20),
            offer_submission_end=date(2025, 6, 5),
            decision=PutOfferDecision.PENDING,
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), today)
    put_ops = [op for op in pending if op.kind == "put_offer_submit"]
    assert len(put_ops) == 1
    assert put_ops[0].urgency == "soon"
    assert put_ops[0].status == "action_required"


def test_put_offer_submit_skipped_when_decision_made() -> None:
    """Если решение уже EXERCISE/HOLD — pending не нужен."""
    p = _trading_portfolio()
    p.positions = [
        _position(
            lots=5,
            actual_lots=5,
            offer_date=date(2025, 6, 20),
            decision=PutOfferDecision.EXERCISE,
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert not any(op.kind == "put_offer_submit" for op in pending)


def test_persisted_top_up_buy_kept_when_no_traderecord() -> None:
    """Сохранённый top_up_buy остаётся, пока нет FILL TradeRecord."""
    p = _trading_portfolio()
    p.positions = [_position(lots=5, actual_lots=5, figi="BBG_X")]
    persisted = PendingOperation(
        kind="top_up_buy",
        isin="RU000_NEW",
        name="Top-up bond",
        lots=2,
        figi="BBG_NEW",
        suggested_price_pct=PriceUnitPct(100.5),
        top_up_batch_id="batch-1",
    )
    p.pending_operations = [persisted]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert any(op.kind == "top_up_buy" for op in pending)


def test_persisted_top_up_buy_filtered_when_filled() -> None:
    """top_up_buy с FILL TradeRecord не показывается."""
    p = _trading_portfolio()
    persisted = PendingOperation(
        kind="top_up_buy",
        isin="RU000_NEW",
        name="Top-up bond",
        lots=2,
        figi="BBG_NEW",
        suggested_price_pct=PriceUnitPct(100.5),
        top_up_batch_id="batch-1",
    )
    p.pending_operations = [persisted]
    p.trade_records = [
        TradeRecord(
            request_uid="u1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG_NEW",
            direction="BUY",
            lots=2,
            status="EXECUTION_REPORT_STATUS_FILL",
            pending_op_id=persisted.id,
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert not any(op.kind == "top_up_buy" for op in pending)


def test_top_up_buy_kept_after_prior_initial_fill_on_same_figi() -> None:
    """Top-up на ту же бумагу не исчезает из-за стартового FILL."""
    p = _trading_portfolio()
    p.positions = [_position(lots=82, actual_lots=66, figi="BBG_VIS", isin="RU000VIS")]
    top_up = PendingOperation(
        kind="top_up_buy",
        isin="RU000VIS",
        name="ВИС Ф БП07",
        lots=16,
        figi="BBG_VIS",
        suggested_price_pct=PriceUnitPct(100.5),
        top_up_batch_id="batch-2",
    )
    p.pending_operations = [top_up]
    p.trade_records = [
        TradeRecord(
            request_uid="u-initial",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG_VIS",
            direction="BUY",
            lots=66,
            status="EXECUTION_REPORT_STATUS_FILL",
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert any(op.kind == "top_up_buy" and op.lots == 16 for op in pending)


def test_initial_buy_shown_when_top_up_gap_after_prior_fill() -> None:
    """Если top_up_buy уже снят, но gap остался — показываем догоняющую покупку."""
    p = _trading_portfolio()
    p.positions = [_position(lots=82, actual_lots=66, figi="BBG_VIS", isin="RU000VIS")]
    p.trade_records = [
        TradeRecord(
            request_uid="u-initial",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG_VIS",
            direction="BUY",
            lots=66,
            status="EXECUTION_REPORT_STATUS_FILL",
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert any(op.kind == "initial_buy" and op.lots == 16 for op in pending)


def test_sweep_completed_pending_removes_filled() -> None:
    """`sweep_completed_pending` удаляет filled-ы из персистенса."""
    p = _trading_portfolio()
    op_filled = PendingOperation(
        kind="manual_sell",
        isin="RU000A1",
        name="Test",
        lots=2,
        figi="BBG1",
    )
    op_open = PendingOperation(
        kind="manual_sell",
        isin="RU000A2",
        name="Test 2",
        lots=3,
        figi="BBG2",
    )
    p.pending_operations = [op_filled, op_open]
    p.trade_records = [
        TradeRecord(
            request_uid="u1",
            account_id="acc",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="SELL",
            lots=2,
            status="EXECUTION_REPORT_STATUS_FILL",
            pending_op_id=op_filled.id,
        )
    ]
    removed = sweep_completed_pending(p)
    assert removed == 1
    assert len(p.pending_operations) == 1
    assert p.pending_operations[0].isin == "RU000A2"


def test_pending_enrich_exposes_pricing_and_dirty_estimate() -> None:
    p = _trading_portfolio()
    p.positions = [_position(lots=2, actual_lots=0)]
    bond = _bond("RU000A1")
    bond.lot_size = 10
    bond.accrued_interest = 12.5
    pending = compute_pending_operations(
        p, _empty_snapshot(), date(2025, 6, 1), universe=[bond]
    )
    op = pending[0]
    assert op.face_value_rub == 1000.0
    assert op.lot_size == 10
    assert op.aci_rub_per_bond == 12.5
    # 2 лота × (10 × (100.5% × 1000 + 12.5 ₽ НКД))
    assert op.estimated_amount_rub == 20_350.0


def test_pending_enrich_uses_broker_nkd_when_moex_aci_missing() -> None:
    p = _trading_portfolio()
    p.positions = [_position(lots=1, actual_lots=0, figi="BBG_MTS")]
    bond = _bond("RU000A1", figi="BBG_MTS")
    bond.accrued_interest = 0.0
    snapshot = AccountSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={
            "BBG_MTS": BondPosition(
                figi="BBG_MTS",
                instrument_uid="uid-mts",
                ticker="MTS05",
                quantity=1,
                lots=1,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(285.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    pending = compute_pending_operations(
        p, snapshot, date(2025, 6, 1), universe=[bond]
    )
    assert pending[0].aci_rub_per_bond == 285.0


def test_initial_buy_has_action_required_status() -> None:
    p = _trading_portfolio()
    p.positions = [_position(lots=5, actual_lots=0)]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert pending[0].status == "action_required"
    assert pending[0].urgency == "normal"
    assert pending[0].estimated_amount_rub is not None


def test_initial_buy_blocked_without_figi() -> None:
    p = _trading_portfolio()
    pos = _position(lots=5, actual_lots=0)
    pos.figi = ""
    p.positions = [pos]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert len(pending) == 1
    assert pending[0].status == "blocked"
    assert pending[0].block_reason is not None


def test_initial_buy_in_progress_when_active_traderecord() -> None:
    p = _trading_portfolio()
    p.positions = [_position(lots=5, actual_lots=0, figi="BBG1")]
    op_id = "test-op-id"
    p.trade_records = [
        TradeRecord(
            request_uid="uid1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="BUY",
            lots=5,
            pending_op_id=op_id,
            order_id="order-123",
            price_pct=100.5,
            status="EXECUTION_REPORT_STATUS_NEW",
            total_order_amount_rub=5050.0,
            initial_commission_rub=10.0,
            lots_executed=0,
        )
    ]
    pending = compute_pending_operations(p, _empty_snapshot(), date(2025, 6, 1))
    assert pending[0].status == "in_progress"
    assert pending[0].active_order_id == "order-123"
    assert pending[0].active_order_lots == 5
    assert pending[0].active_order_price_pct == pytest.approx(100.5)
    assert pending[0].active_order_total_rub == pytest.approx(5050.0)
    assert pending[0].active_order_commission_rub == pytest.approx(10.0)
    assert pending[0].active_order_lots_executed == 0
    assert pending[0].active_order_bonds_count == 50


def test_reinvest_buy_uses_universe_for_lots_and_figi() -> None:
    p = _trading_portfolio()
    bond = BondRecord(
        secid="OFZ1",
        isin="RU000OFZ",
        name="ОФЗ тест",
        maturity_date=date(2027, 1, 1),
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
    bond.figi = "FIGI_OFZ"
    slot = ReinvestmentSlot(
        trigger_date=date(2025, 5, 1),
        trigger_reason=ReinvestmentTriggerReason.MATURITY,
        expected_cash_rub=25_000.0,
        suggested_isin="RU000OFZ",
        gap_days=2,
        source_position_isin="RU000SRC",
    )
    pending = compute_pending_operations(
        p,
        _empty_snapshot(),
        date(2025, 6, 1),
        universe=[bond],
        resolved_slots=[slot],
    )
    assert len(pending) == 1
    assert pending[0].kind == "reinvest_buy"
    assert pending[0].lots == 25
    assert pending[0].figi == "FIGI_OFZ"
    assert pending[0].name == "ОФЗ тест"


def test_reinvest_buy_overdue_after_grace_period() -> None:
    p = _trading_portfolio()
    bond = BondRecord(
        secid="OFZ1",
        isin="RU000OFZ",
        name="ОФЗ тест",
        maturity_date=date(2027, 1, 1),
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
    bond.figi = "FIGI_OFZ"
    slot = ReinvestmentSlot(
        trigger_date=date(2025, 5, 1),
        trigger_reason=ReinvestmentTriggerReason.MATURITY,
        expected_cash_rub=10_000.0,
        suggested_isin="RU000OFZ",
        gap_days=2,
    )
    pending = compute_pending_operations(
        p,
        _empty_snapshot(),
        date(2025, 6, 10),
        universe=[bond],
        resolved_slots=[slot],
    )
    assert pending[0].status == "overdue"
    assert pending[0].urgency == "critical"


def test_reinvest_buys_sorted_by_due_date() -> None:
    """Несколько reinvest_buy с одинаковой срочностью идут по возрастанию due_date."""
    p = _trading_portfolio()

    def _bond(isin: str, name: str) -> BondRecord:
        bond = BondRecord(
            secid=isin[:6],
            isin=isin,
            name=name,
            maturity_date=date(2027, 1, 1),
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
        bond.figi = f"FIGI_{isin}"
        return bond

    bond_early = _bond("RU000EARLY", "ОФЗ ранняя")
    bond_late = _bond("RU000LATE", "ОФЗ поздняя")
    slot_later = ReinvestmentSlot(
        trigger_date=date(2025, 5, 15),
        trigger_reason=ReinvestmentTriggerReason.MATURITY,
        expected_cash_rub=10_000.0,
        suggested_isin=bond_late.isin,
        gap_days=2,
        source_position_isin="RU000SRC2",
    )
    slot_earlier = ReinvestmentSlot(
        trigger_date=date(2025, 5, 1),
        trigger_reason=ReinvestmentTriggerReason.MATURITY,
        expected_cash_rub=10_000.0,
        suggested_isin=bond_early.isin,
        gap_days=2,
        source_position_isin="RU000SRC1",
    )

    pending = compute_pending_operations(
        p,
        _empty_snapshot(),
        date(2025, 6, 1),
        universe=[bond_early, bond_late],
        resolved_slots=[slot_later, slot_earlier],
    )

    reinvest_ops = [op for op in pending if op.kind == "reinvest_buy"]
    assert len(reinvest_ops) == 2
    assert reinvest_ops[0].due_date == date(2025, 5, 1)
    assert reinvest_ops[1].due_date == date(2025, 5, 15)
