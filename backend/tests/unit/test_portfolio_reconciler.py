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
    AccountKind,
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.reconciler import (
    detect_top_up,
    reconcile_positions,
    validate_account_for_attach,
)
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


def test_reconcile_detects_unknown_broker_bond() -> None:
    """Бумага на счёте не из портфеля — critical drift."""
    portfolio = _portfolio()
    portfolio.positions = []  # портфель пуст
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
    assert any(d.severity == "critical" for d in result.drifts)


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
