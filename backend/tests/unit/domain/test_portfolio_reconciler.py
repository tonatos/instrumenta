"""
Тесты `core.portfolio_reconciler`:

* `validate_account_for_attach` — strict-режим
* `reconcile_positions` — обновление actual_lots, выявление drift
* `detect_top_up` — обнаружение INPUT-операций
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
)
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.reconciler import (
    TopUpDetection,
    adopt_orphan_holdings,
    detect_top_up,
    migrate_legacy_adopted_holdings,
    reconcile_acknowledged_top_ups,
    reconcile_held_position_targets,
    reconcile_positions,
    sweep_phantom_top_up_positions,
    top_up_amount_to_distribute,
    validate_account_for_attach,
)
from bond_monitor.domain.trading.ports import BrokerBondPosition, BrokerSnapshot
from bond_monitor.domain.trading.models import PendingOperation, TradeRecord
from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    BondPosition,
    OperationRecord,
    OtherInstrument,
)


def _empty_snapshot(money_rub: float) -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money_rub),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _portfolio(initial_amount: float = 100_000.0) -> Portfolio:
    return Portfolio(
        name="Test",
        initial_amount_rub=initial_amount,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )


# ── validate_account_for_attach ──────────────────────────────────────────────


def test_validate_clean_account_ok() -> None:
    """Чистый счёт с money_rub == initial_amount → can_attach=True."""
    portfolio = _portfolio(100_000.0)
    snapshot = _empty_snapshot(100_000.0)
    result = validate_account_for_attach(snapshot, portfolio)
    assert result.can_attach is True
    assert not result.blockers


def test_validate_blocks_foreign_instruments() -> None:
    """Акции/валюта/etf на счёте → блокер."""
    portfolio = _portfolio(100_000.0)
    snapshot = AccountSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(100_000.0),
        bond_positions={},
        other_instruments=[
            OtherInstrument(
                instrument_type="share",
                figi="BBG0SHARE",
                ticker="SBER",
                quantity=10,
            )
        ],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    result = validate_account_for_attach(snapshot, portfolio)
    assert result.can_attach is False
    assert any("SBER" in b for b in result.blockers)


def test_validate_blocks_existing_bonds() -> None:
    """Бумаги на счёте → блокер (свежий портфель должен начинать с нуля)."""
    portfolio = _portfolio(100_000.0)
    snapshot = AccountSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(100_000.0),
        bond_positions={
            "BBG0BOND": BondPosition(
                figi="BBG0BOND",
                instrument_uid="uid",
                ticker="OFZ26242",
                quantity=10,
                lots=1,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(5.0),
                average_price_pct=PriceUnitPct(99.5),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    result = validate_account_for_attach(snapshot, portfolio)
    assert result.can_attach is False
    assert any("OFZ26242" in b for b in result.blockers)


def test_validate_blocks_insufficient_cash() -> None:
    """money_rub < initial_amount → блокер."""
    portfolio = _portfolio(100_000.0)
    snapshot = _empty_snapshot(50_000.0)
    result = validate_account_for_attach(snapshot, portfolio)
    assert result.can_attach is False
    assert any("50" in b or "не хватает" in b.lower() for b in result.blockers)


def test_validate_excess_cash_warns_and_ups_budget() -> None:
    """money_rub > initial_amount → warning + бюджет поднимается."""
    portfolio = _portfolio(100_000.0)
    snapshot = _empty_snapshot(150_000.0)
    result = validate_account_for_attach(snapshot, portfolio)
    assert result.can_attach is True
    assert result.effective_initial_amount_rub == 150_000.0
    assert result.warnings  # должно быть хотя бы одно предупреждение


# ── reconcile_positions ──────────────────────────────────────────────────────


def _position(isin: str = "RU000A1", lots: int = 5, figi: str | None = "BBG1") -> PortfolioPosition:
    return PortfolioPosition(
        isin=isin,
        secid="TEST",
        name="Test bond",
        lots=lots,
        lot_size=10,
        purchase_clean_price_pct=100.0,
        purchase_dirty_price_rub=1000.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2025, 1, 1),
        purchase_amount_rub=lots * 10 * 1000.0,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=date(2027, 1, 1),
        offer_date=None,
        coupon_period_days=180,
        source=PositionSourceType.INITIAL,
        figi=figi,
    )


def test_reconcile_sets_actual_lots_from_snapshot() -> None:
    """`actual_lots` = quantity / lot_size из снапшота."""
    portfolio = _portfolio()
    portfolio.positions = [_position(lots=5)]
    snapshot = AccountSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={
            "BBG1": BondPosition(
                figi="BBG1",
                instrument_uid="uid",
                ticker="TEST",
                quantity=50,  # 50 bonds = 5 лотов × 10
                lots=5,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    result = reconcile_positions(portfolio, snapshot)
    assert portfolio.positions[0].actual_lots == 5
    assert not result.drifts


def test_reconcile_detects_missing_position() -> None:
    """Бумага в плане, но не на счёте — actual_lots=0, drift warning."""
    portfolio = _portfolio()
    portfolio.positions = [_position(lots=5)]
    snapshot = _empty_snapshot(50_000.0)
    result = reconcile_positions(portfolio, snapshot)
    assert portfolio.positions[0].actual_lots == 0
    assert any(d.severity == "warning" for d in result.drifts)


def test_reconcile_ignores_unknown_broker_bond_in_reverse_pass() -> None:
    """Обратная сверка больше не помечает чужие бумаги как critical — adoption отдельно."""
    portfolio = _portfolio()
    portfolio.positions = []
    snapshot = AccountSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={
            "BBG_UNKNOWN": BondPosition(
                figi="BBG_UNKNOWN",
                instrument_uid="uid",
                ticker="WTF",
                quantity=10,
                lots=1,
                blocked=0,
                current_price_pct=None,
                current_nkd_rub=None,
                average_price_pct=None,
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    result = reconcile_positions(portfolio, snapshot)
    assert not any(d.severity == "critical" for d in result.drifts)


# ── detect_top_up ────────────────────────────────────────────────────────────


def test_detect_top_up_finds_recent_inputs() -> None:
    """INPUT после `last_top_up_processed_at` суммируется."""
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.last_top_up_processed_at = "2025-01-01T00:00:00+00:00"

    operations = [
        OperationRecord(
            id="op1",
            type="OPERATION_TYPE_INPUT",
            state="EXECUTED",
            date=datetime(2025, 6, 1, tzinfo=UTC),
            figi="",
            instrument_uid="",
            instrument_type="",
            payment_rub=Rub(50_000.0),
            quantity=0,
            price_pct=None,
            commission_rub=None,
        ),
    ]
    snapshot = _empty_snapshot(200_000.0)
    result = detect_top_up(portfolio, operations, snapshot)
    assert result.pending_top_up_rub == 50_000.0
    assert result.has_pending_top_up


def test_detect_top_up_ignores_old_inputs() -> None:
    """INPUT до `last_top_up_processed_at` не учитывается."""
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.last_top_up_processed_at = "2025-06-01T00:00:00+00:00"

    operations = [
        OperationRecord(
            id="op1",
            type="OPERATION_TYPE_INPUT",
            state="EXECUTED",
            date=datetime(2025, 1, 1, tzinfo=UTC),  # ДО reference
            figi="",
            instrument_uid="",
            instrument_type="",
            payment_rub=Rub(50_000.0),
            quantity=0,
            price_pct=None,
            commission_rub=None,
        ),
    ]
    snapshot = _empty_snapshot(200_000.0)
    result = detect_top_up(portfolio, operations, snapshot)
    assert result.pending_top_up_rub == 0.0
    assert not result.has_pending_top_up


def test_detect_top_up_limited_by_cash() -> None:
    """available ≤ money_rub × (1 - buffer)."""
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.last_top_up_processed_at = "2025-01-01T00:00:00+00:00"

    operations = [
        OperationRecord(
            id="op1",
            type="OPERATION_TYPE_INPUT",
            state="EXECUTED",
            date=datetime(2025, 6, 1, tzinfo=UTC),
            figi="",
            instrument_uid="",
            instrument_type="",
            payment_rub=Rub(100_000.0),
            quantity=0,
            price_pct=None,
            commission_rub=None,
        ),
    ]
    # money_rub = 20 000 ₽ ← меньше, чем INPUT
    snapshot = _empty_snapshot(20_000.0)
    result = detect_top_up(portfolio, operations, snapshot)
    assert result.pending_top_up_rub == 100_000.0
    # available ограничено реальным cash: 20 000 × (1 − 0.005) = 19 900
    assert result.available_for_distribution_rub == pytest.approx(19_900.0)


def test_top_up_amount_to_distribute_prefers_fresh_input() -> None:
    detection = TopUpDetection(
        pending_top_up_rub=Rub(50_000.0),
        available_for_distribution_rub=Rub(40_000.0),
        input_operations=[],
        from_date=date(2025, 1, 1),
    )
    amount, note = top_up_amount_to_distribute(detection, free_cash_rub=30_000.0)
    assert amount == pytest.approx(30_000.0)
    assert note is None


def test_top_up_amount_to_distribute_orphan_cash_without_input() -> None:
    detection = TopUpDetection(
        pending_top_up_rub=Rub(0.0),
        available_for_distribution_rub=Rub(0.0),
        input_operations=[],
        from_date=date(2025, 6, 1),
    )
    amount, note = top_up_amount_to_distribute(detection, free_cash_rub=182_000.0)
    assert amount == pytest.approx(182_000.0)
    assert note is not None
    assert "Свободный кэш" in note


def test_adopt_orphan_holdings_creates_position_from_account() -> None:
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    bond = BondRecord(
        secid="TG2",
        isin="RU000A109TG2",
        name="iКарРус1P4",
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
    bond.figi = "BBG0TG2"
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={
            "BBG0TG2": BrokerBondPosition(
                figi="BBG0TG2",
                instrument_uid="uid",
                ticker="TG2",
                quantity=6,
                lots=6,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-1",
            account_id="acc",
            account_kind=AccountKind.SANDBOX,
            figi="BBG0TG2",
            direction="BUY",
            lots=28,
            order_id="order-tg2",
            status="EXECUTION_REPORT_STATUS_NEW",
            lots_executed=0,
        )
    ]
    notes = adopt_orphan_holdings(
        portfolio,
        snapshot,
        {bond.isin: bond},
        today=date(2026, 7, 8),
    )
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].isin == "RU000A109TG2"
    assert portfolio.positions[0].lots == 34
    assert portfolio.positions[0].actual_lots == 6
    assert portfolio.positions[0].source == PositionSourceType.ADOPTED
    assert notes


def test_adopt_orphan_holdings_resyncs_adopted_lots_when_order_cancelled() -> None:
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    bond = BondRecord(
        secid="TG2",
        isin="RU000A109TG2",
        name="iКарРус1P4",
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
    bond.figi = "BBG0TG2"
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A109TG2",
            secid="TG2",
            name="iКарРус1P4",
            lots=34,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 7, 8),
            purchase_amount_rub=34_000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=180,
            source=PositionSourceType.ADOPTED,
            figi="BBG0TG2",
            actual_lots=6,
        )
    ]
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-1",
            account_id="acc",
            account_kind=AccountKind.SANDBOX,
            figi="BBG0TG2",
            direction="BUY",
            lots=28,
            order_id="order-tg2",
            status="EXECUTION_REPORT_STATUS_CANCELLED",
            lots_executed=0,
        )
    ]
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(2_000.0),
        bond_positions={
            "BBG0TG2": BrokerBondPosition(
                figi="BBG0TG2",
                instrument_uid="uid",
                ticker="TG2",
                quantity=6,
                lots=6,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    adopt_orphan_holdings(
        portfolio,
        snapshot,
        {bond.isin: bond},
        today=date(2026, 7, 8),
    )

    assert portfolio.positions[0].lots == 6
    assert portfolio.positions[0].actual_lots == 6


def test_migrate_legacy_adopted_collapses_inflated_initial_position() -> None:
    """Легаси: adopt_orphan_holdings пометил позицию как INITIAL с lots=held+cancelled."""
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A109TG2",
            secid="TG2",
            name="iКарРус1P4",
            lots=36,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 7, 7),
            purchase_amount_rub=36_000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=180,
            source=PositionSourceType.INITIAL,
            figi="BBG0TG2",
            actual_lots=8,
        )
    ]
    portfolio.pending_operations = [
        PendingOperation(
            kind="top_up_buy",
            isin="RU000A109TG2",
            name="iКарРус1P4",
            lots=16,
            figi="BBG0TG2",
            top_up_batch_id="batch-1",
        )
    ]
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-fill",
            account_id="acc",
            account_kind=AccountKind.SANDBOX,
            figi="BBG0TG2",
            direction="BUY",
            lots=6,
            order_id="order-fill",
            status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=6,
        ),
        TradeRecord(
            request_uid="uid-cancel",
            account_id="acc",
            account_kind=AccountKind.SANDBOX,
            figi="BBG0TG2",
            direction="BUY",
            lots=28,
            order_id="order-cancel",
            status="EXECUTION_REPORT_STATUS_CANCELLED",
            lots_executed=0,
        ),
    ]
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(2_000.0),
        bond_positions={
            "BBG0TG2": BrokerBondPosition(
                figi="BBG0TG2",
                instrument_uid="uid",
                ticker="TG2",
                quantity=8,
                lots=8,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    notes = migrate_legacy_adopted_holdings(portfolio, snapshot, {})

    assert portfolio.positions[0].source == PositionSourceType.ADOPTED
    assert portfolio.positions[0].lots == 8
    assert notes


def test_migrate_legacy_skips_legitimate_partial_initial_buy() -> None:
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A1",
            secid="TST",
            name="Test bond",
            lots=10,
            lot_size=10,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 1, 1),
            purchase_amount_rub=10_000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=180,
            source=PositionSourceType.INITIAL,
            figi="BBG1",
            actual_lots=5,
        )
    ]
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid-fill",
            account_id="acc",
            account_kind=AccountKind.SANDBOX,
            figi="BBG1",
            direction="BUY",
            lots=5,
            order_id="order-fill",
            status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=5,
        )
    ]
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={
            "BBG1": BrokerBondPosition(
                figi="BBG1",
                instrument_uid="uid",
                ticker="TST",
                quantity=50,
                lots=5,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    migrate_legacy_adopted_holdings(portfolio, snapshot, {})

    assert portfolio.positions[0].source == PositionSourceType.INITIAL
    assert portfolio.positions[0].lots == 10


def test_sweep_phantom_top_up_removes_unmaterialized_new_position() -> None:
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.top_up_batch_meta = {
        "batch-phantom": {
            "previous_watermark": "2026-07-07T19:00:00+00:00",
            "distributed_amount_rub": 30_000.0,
            "allocations": [
                {"isin": "RU000A107BH2", "lots": 30, "is_new_position": True},
            ],
        }
    }
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A107BH2",
            secid="BH2",
            name="ИЛСБО-1-1Р",
            lots=30,
            lot_size=1,
            purchase_clean_price_pct=97.5,
            purchase_dirty_price_rub=983.33,
            purchase_aci_rub=8.33,
            purchase_date=date(2026, 7, 8),
            purchase_amount_rub=29_499.9,
            coupon_rate=19.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=30,
            source=PositionSourceType.INITIAL,
            figi="FIGI_BH2",
            actual_lots=0,
        )
    ]
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(2_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    notes = sweep_phantom_top_up_positions(portfolio, snapshot)

    assert portfolio.positions == []
    assert notes


def test_reconcile_held_position_targets_collapses_inflated_lots() -> None:
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A109TG2",
            secid="TG2",
            name="iКарРус1P4",
            lots=36,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 7, 7),
            purchase_amount_rub=36_000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=180,
            source=PositionSourceType.INITIAL,
            figi="BBG0TG2",
            actual_lots=8,
        )
    ]
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(2_000.0),
        bond_positions={
            "BBG0TG2": BrokerBondPosition(
                figi="BBG0TG2",
                instrument_uid="uid",
                ticker="TG2",
                quantity=8,
                lots=8,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )

    notes = reconcile_held_position_targets(portfolio, snapshot)

    assert portfolio.positions[0].lots == 8
    assert portfolio.positions[0].source == PositionSourceType.ADOPTED
    assert notes


def test_adopt_orphan_holdings_unknown_bond_returns_note_only() -> None:
    portfolio = _portfolio()
    portfolio.mode = PortfolioMode.TRADING
    snapshot = BrokerSnapshot(
        account_id="acc",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(50_000.0),
        bond_positions={
            "BBG_UNKNOWN": BrokerBondPosition(
                figi="BBG_UNKNOWN",
                instrument_uid="uid",
                ticker="WTF",
                quantity=10,
                lots=10,
                blocked=0,
                current_price_pct=None,
                current_nkd_rub=None,
                average_price_pct=None,
            )
        },
        other_instruments=[],
        fetched_at="2026-01-01T00:00:00+00:00",
    )
    notes = adopt_orphan_holdings(portfolio, snapshot, {}, today=date(2026, 7, 8))
    assert not portfolio.positions
    assert notes
    assert "universe" in notes[0].lower() or "не найдена" in notes[0]


def test_reconcile_acknowledged_top_ups_from_positions() -> None:
    """Sync поднимает acknowledged_top_ups, если на счёте больше initial."""
    portfolio = _portfolio(initial_amount=20_000.0)
    portfolio.mode = PortfolioMode.TRADING
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A100PB0",
            secid="RU000A100PB0",
            name="Test bond",
            lots=175,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1_000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 1, 1),
            purchase_amount_rub=175_000.0,
            coupon_rate=20.0,
            face_value=1_000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=182,
            source=PositionSourceType.INITIAL,
            actual_lots=175,
        ),
    ]
    snapshot = _empty_snapshot(5_000.0)
    portfolio.positions[0].figi = "FIGI1"

    reconcile_acknowledged_top_ups(portfolio, snapshot)

    assert portfolio.acknowledged_top_ups_rub == pytest.approx(160_000.0)


def test_reconcile_acknowledged_top_ups_syncs_down_when_inflated() -> None:
    """Sync снижает acknowledged_top_ups, если на счёте меньше метаданных."""
    portfolio = _portfolio(initial_amount=20_000.0)
    portfolio.mode = PortfolioMode.TRADING
    portfolio.acknowledged_top_ups_rub = 227_738.0
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A100PB0",
            secid="RU000A100PB0",
            name="Test bond",
            lots=175,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1_000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 1, 1),
            purchase_amount_rub=175_000.0,
            coupon_rate=20.0,
            face_value=1_000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=182,
            source=PositionSourceType.INITIAL,
            actual_lots=175,
        ),
    ]
    snapshot = _empty_snapshot(5_000.0)

    assert reconcile_acknowledged_top_ups(portfolio, snapshot)

    assert portfolio.acknowledged_top_ups_rub == pytest.approx(160_000.0)
