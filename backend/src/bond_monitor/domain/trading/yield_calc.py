"""
Расчёт фактической доходности портфеля по операциям T-Invest.

XIRR (eXtended Internal Rate of Return) — годовая доходность с учётом
неравномерных по времени cashflow-ов. Аналог формулы Excel ``XIRR``.

Логика:

* Считаем cashflow для портфеля как **знаковый** список:
  + покупка облигации → -сумма (отток),
  + купон / погашение / продажа → +сумма (приток),
  + текущая рыночная оценка позиций на ``as_of`` → +сумма (мнимый приток),
  + начальное пополнение счёта НЕ учитываем как cashflow (это «вклад»,
    не доход портфеля — XIRR должен мерить доходность инвестиций,
    не пополнения).
* Фильтруем операции по ISIN-ам портфеля + комиссии/налоги, относящиеся
  к этим бумагам.
* Используем ``pyxirr.xirr`` для численного решения уравнения NPV = 0.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.trading.ports import BrokerOperation, BrokerSnapshot

logger = logging.getLogger(__name__)


# Имена `OPERATION_TYPE_*` (как строки из `BrokerOperation.type`),
# которые входят в cashflow портфеля. Подбор не случайный: только то,
# что напрямую связано с конкретной облигацией (BUY/SELL/COUPON/...).
# INPUT/OUTPUT в cashflow XIRR не входят — это пополнения/выводы со
# счёта, а не доход.
_INFLOW_TYPES: frozenset[str] = frozenset(
    {
        "OPERATION_TYPE_SELL",
        "OPERATION_TYPE_COUPON",
        "OPERATION_TYPE_BOND_REPAYMENT",
        "OPERATION_TYPE_BOND_REPAYMENT_FULL",
    }
)

_OUTFLOW_TYPES: frozenset[str] = frozenset(
    {
        "OPERATION_TYPE_BUY",
        "OPERATION_TYPE_BUY_CARD",
        "OPERATION_TYPE_BUY_MARGIN",
    }
)

# Налоги / комиссии вычитаются из «достижений» (отрицательный знак,
# уменьшают итог).
_TAX_FEE_TYPES: frozenset[str] = frozenset(
    {
        "OPERATION_TYPE_BOND_TAX",
        "OPERATION_TYPE_BOND_TAX_PROGRESSIVE",
        "OPERATION_TYPE_TAX",
        "OPERATION_TYPE_TAX_PROGRESSIVE",
        "OPERATION_TYPE_TAX_CORRECTION",
        "OPERATION_TYPE_TAX_CORRECTION_COUPON",
        "OPERATION_TYPE_BROKER_FEE",
        "OPERATION_TYPE_SERVICE_FEE",
        "OPERATION_TYPE_OTHER_FEE",
    }
)


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class ActualPerformance:
    """Сводка по фактической доходности портфеля в режиме торговли.

    Все суммы в ₽, доходности в годовых % (например, ``14.5`` = 14.5%).
    """

    xirr_pct: float | None
    coupons_received_rub: Rub
    tax_paid_rub: Rub
    commission_paid_rub: Rub
    realized_profit_rub: Rub  # cash + sell - buy за период
    unrealized_value_rub: Rub  # рыночная оценка ещё не проданных позиций
    invested_rub: Rub  # сумма всех BUY за период (без top-up)
    received_rub: Rub  # сумма всех SELL + COUPON + REPAYMENT
    as_of: str  # ISO-таймстамп оценки


# ── XIRR core ────────────────────────────────────────────────────────────────


def _filter_portfolio_operations(
    operations: list[BrokerOperation],
    *,
    figis: set[str],
) -> list[BrokerOperation]:
    """Отфильтровать операции, относящиеся к бумагам портфеля.

    Учитываем все операции с ``figi`` из ``figis`` (BUY/SELL/COUPON/...) +
    налоги/комиссии без figi (которые часто относятся к нескольким
    бумагам сразу — считаем их косвенно «своими»).

    Это эвристика: налоги/комиссии без явной привязки идут «на пользу/
    в ущерб» XIRR пропорционально, но для портфельной оценки этого
    хватает.
    """
    result: list[BrokerOperation] = []
    for op in operations:
        if op.figi and op.figi in figis:
            result.append(op)
        elif not op.figi and op.type in _TAX_FEE_TYPES:
            # Налоги/комиссии без figi — попадают в общий cashflow.
            result.append(op)
    return result


def _to_xirr_cashflow(
    operations: list[BrokerOperation],
    *,
    as_of: datetime,
    current_value_rub: Rub,
) -> list[tuple[datetime, float]]:
    """Преобразовать операции в `(date, amount)` cashflow для XIRR.

    Соглашение знаков: payment в T-Invest API уже знаковый
    (BUY → отрицательный, SELL/COUPON → положительный) — берём как есть.
    """
    cashflow: list[tuple[datetime, float]] = []
    for op in operations:
        if op.payment_rub is None:
            continue
        if op.type in _INFLOW_TYPES or op.type in _OUTFLOW_TYPES or op.type in _TAX_FEE_TYPES:
            cashflow.append((op.date, float(op.payment_rub)))

    # Мнимый «возврат» на as_of — текущая рыночная оценка ещё не проданных
    # позиций. Без этого XIRR будет отрицательным (BUY есть, SELL ещё нет).
    if current_value_rub > 0:
        cashflow.append((as_of, float(current_value_rub)))
    return cashflow


def calculate_portfolio_xirr(
    operations: list[BrokerOperation],
    *,
    figis: set[str],
    current_value_rub: Rub,
    as_of: datetime | None = None,
) -> float | None:
    """Годовой XIRR портфеля по операциям + текущая оценка.

    Args:
        operations: Список операций счёта (все типы; фильтрация внутри).
        figis: FIGI бумаг, которые входят в портфель — операции с
            другими figi игнорируются (важно когда на счёте есть бумаги
            от других портфелей, хотя в strict-режиме их быть не должно).
        current_value_rub: Текущая рыночная стоимость **ещё не проданных**
            позиций портфеля. Используется как «мнимый» приток на дату
            оценки — без неё XIRR будет отрицательным, потому что BUY
            ушли, а SELL ещё нет.
        as_of: Точка оценки (по умолчанию now). Должна быть в UTC.

    Returns:
        Годовая доходность в **% годовых** (например, ``12.5`` = 12.5%),
        или ``None`` если данных недостаточно (нет операций / решение
        не сходится).
    """
    if as_of is None:
        as_of = datetime.now(UTC)

    portfolio_ops = _filter_portfolio_operations(operations, figis=figis)
    if not portfolio_ops:
        return None

    cashflow = _to_xirr_cashflow(portfolio_ops, as_of=as_of, current_value_rub=current_value_rub)
    if len(cashflow) < 2:
        return None
    has_positive = any(amount > 0 for _, amount in cashflow)
    has_negative = any(amount < 0 for _, amount in cashflow)
    if not (has_positive and has_negative):
        return None

    try:
        from pyxirr import InvalidPaymentsError, xirr
    except ImportError:
        logger.error("pyxirr is not installed — XIRR calculation unavailable")
        return None

    dates = [d.date() if isinstance(d, datetime) else d for d, _ in cashflow]
    amounts = [amount for _, amount in cashflow]
    try:
        rate = xirr(dates, amounts)
    except (InvalidPaymentsError, ValueError, OverflowError) as exc:
        logger.warning("xirr() failed: %s", exc)
        return None
    if rate is None:
        return None
    return float(rate) * 100.0


# ── Summary ──────────────────────────────────────────────────────────────────


def _sum_payments(
    operations: list[BrokerOperation],
    *,
    types: frozenset[str],
    figis: set[str],
) -> Rub:
    total: float = 0.0
    for op in operations:
        if op.type not in types:
            continue
        if op.figi and op.figi not in figis:
            continue
        if op.payment_rub is None:
            continue
        total += float(op.payment_rub)
    return Rub(total)


def _estimate_current_value(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
) -> Rub:
    """Сумма ``dirty_price × quantity`` по позициям портфеля на снапшоте."""
    total: float = 0.0
    portfolio_figis = {p.figi for p in portfolio.positions if p.figi}
    for figi, broker_pos in snapshot.bond_positions.items():
        if figi not in portfolio_figis:
            continue
        # current_price_pct в `BondPosition` — чистая цена в % от номинала
        # (конвертируется из ₽ в trading_client при разборе getPortfolio).
        position = next((p for p in portfolio.positions if p.figi == figi), None)
        if position is None:
            continue
        if broker_pos.current_price_pct is None:
            # Нет live-цены — оцениваем по номиналу.
            clean_per_bond = position.face_value
        else:
            clean_per_bond = broker_pos.current_price_pct / 100.0 * position.face_value
        nkd = float(broker_pos.current_nkd_rub or 0.0)
        dirty_per_bond = clean_per_bond + nkd
        total += dirty_per_bond * broker_pos.quantity
    return Rub(total)


def summarize_actual_performance(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    operations: list[BrokerOperation],
    *,
    as_of: datetime | None = None,
) -> ActualPerformance:
    """Полная сводка фактической доходности для UI-карточки.

    Считает: XIRR, сумму купонов, налогов, комиссий, реализованную и
    нереализованную прибыль по операциям за период с
    ``trading_started_at``. Корректно работает даже если операций мало
    или нет (отдаст ``xirr_pct=None`` и нули).
    """
    if as_of is None:
        as_of = datetime.now(UTC)

    figis = {p.figi for p in portfolio.positions if p.figi}
    if not figis:
        # У портфеля ещё нет figi (не привязан к счёту) — возвращаем нули.
        return ActualPerformance(
            xirr_pct=None,
            coupons_received_rub=Rub(0.0),
            tax_paid_rub=Rub(0.0),
            commission_paid_rub=Rub(0.0),
            realized_profit_rub=Rub(0.0),
            unrealized_value_rub=Rub(0.0),
            invested_rub=Rub(0.0),
            received_rub=Rub(0.0),
            as_of=as_of.isoformat(timespec="seconds"),
        )

    coupons = _sum_payments(
        operations,
        types=frozenset({"OPERATION_TYPE_COUPON"}),
        figis=figis,
    )
    tax_paid = Rub(
        -float(
            _sum_payments(
                operations,
                types=frozenset(
                    {
                        "OPERATION_TYPE_BOND_TAX",
                        "OPERATION_TYPE_BOND_TAX_PROGRESSIVE",
                        "OPERATION_TYPE_TAX",
                        "OPERATION_TYPE_TAX_PROGRESSIVE",
                        "OPERATION_TYPE_TAX_CORRECTION",
                        "OPERATION_TYPE_TAX_CORRECTION_COUPON",
                    }
                ),
                figis=figis,
            )
        )
    )
    commission = Rub(
        -float(
            _sum_payments(
                operations,
                types=frozenset(
                    {
                        "OPERATION_TYPE_BROKER_FEE",
                        "OPERATION_TYPE_SERVICE_FEE",
                        "OPERATION_TYPE_OTHER_FEE",
                    }
                ),
                figis=figis,
            )
        )
    )
    invested = Rub(
        -float(
            _sum_payments(
                operations,
                types=_OUTFLOW_TYPES,
                figis=figis,
            )
        )
    )  # BUY с отрицательным payment → инвертируем знак
    received_pos = _sum_payments(
        operations,
        types=_INFLOW_TYPES,
        figis=figis,
    )

    current_value = _estimate_current_value(portfolio, snapshot)
    realized = Rub(float(received_pos) - float(invested))

    xirr_pct = calculate_portfolio_xirr(
        operations,
        figis=figis,
        current_value_rub=current_value,
        as_of=as_of,
    )

    return ActualPerformance(
        xirr_pct=xirr_pct,
        coupons_received_rub=coupons,
        tax_paid_rub=tax_paid,
        commission_paid_rub=commission,
        realized_profit_rub=realized,
        unrealized_value_rub=current_value,
        invested_rub=invested,
        received_rub=received_pos,
        as_of=as_of.isoformat(timespec="seconds"),
    )


__all__ = [
    "ActualPerformance",
    "calculate_portfolio_xirr",
    "summarize_actual_performance",
]
