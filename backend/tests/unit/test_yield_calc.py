"""
Тесты `core.yield_calc.calculate_portfolio_xirr` и `summarize_actual_performance`.

Все тесты — синтетические `OperationRecord`, без сети.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.yield_calc import calculate_portfolio_xirr
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord


def _op(
    type_: str,
    date_iso: str,
    figi: str = "BBG1",
    payment: float = 0.0,
    quantity: int = 0,
    price_pct: float | None = None,
) -> OperationRecord:
    return OperationRecord(
        id=f"{type_}-{date_iso}",
        type=type_,
        state="OPERATION_STATE_EXECUTED",
        date=datetime.fromisoformat(date_iso).replace(tzinfo=UTC),
        figi=figi,
        instrument_uid="uid",
        instrument_type="bond",
        payment_rub=Rub(payment),
        quantity=quantity,
        price_pct=(PriceUnitPct(price_pct) if price_pct is not None else None),
        commission_rub=None,
    )


def test_xirr_buy_then_coupon_one_year_positive() -> None:
    """BUY -1000, COUPON +60 спустя полгода, eval через год с current 1000."""
    ops = [
        _op("OPERATION_TYPE_BUY", "2025-01-01", payment=-1000.0, quantity=1),
        _op("OPERATION_TYPE_COUPON", "2025-07-01", payment=60.0),
    ]
    rate = calculate_portfolio_xirr(
        ops,
        figis={"BBG1"},
        current_value_rub=Rub(1000.0),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert rate is not None
    # Доходность около 6% годовых.
    assert 5.0 < rate < 7.0


def test_xirr_empty_returns_none() -> None:
    """Без операций — нет смысла считать XIRR."""
    assert (
        calculate_portfolio_xirr(
            [],
            figis={"BBG1"},
            current_value_rub=Rub(0.0),
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
        )
        is None
    )


def test_xirr_only_buys_no_inflows() -> None:
    """Только BUY, current_value=0 — нет положительных потоков, XIRR=None."""
    ops = [
        _op("OPERATION_TYPE_BUY", "2025-01-01", payment=-1000.0, quantity=1),
    ]
    rate = calculate_portfolio_xirr(
        ops,
        figis={"BBG1"},
        current_value_rub=Rub(0.0),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert rate is None


def test_xirr_filters_by_figi() -> None:
    """Операции по чужому figi игнорируются."""
    ops = [
        _op("OPERATION_TYPE_BUY", "2025-01-01", figi="BBG1", payment=-1000.0, quantity=1),
        _op("OPERATION_TYPE_BUY", "2025-01-02", figi="BBG2", payment=-5000.0, quantity=5),
    ]
    rate = calculate_portfolio_xirr(
        ops,
        figis={"BBG1"},  # игнорим BBG2
        current_value_rub=Rub(1100.0),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
    )
    # Если бы BBG2 учитывался — рост был бы катастрофически отрицательным
    # (-5000 ушло, не вернулось). Без него — небольшой плюс ~10%.
    assert rate is not None
    assert 8.0 < rate < 12.0


def test_xirr_buy_sell_round_trip_zero_profit() -> None:
    """Купил и продал за ту же сумму — XIRR близок к 0."""
    ops = [
        _op("OPERATION_TYPE_BUY", "2025-01-01", payment=-1000.0, quantity=1),
        _op("OPERATION_TYPE_SELL", "2025-12-31", payment=1000.0, quantity=1),
    ]
    rate = calculate_portfolio_xirr(
        ops,
        figis={"BBG1"},
        current_value_rub=Rub(0.0),
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert rate is not None
    assert abs(rate) < 1.0  # очень близко к нулю
