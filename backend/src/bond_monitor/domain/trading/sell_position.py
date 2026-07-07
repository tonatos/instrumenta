"""Валидация и очередь продажи позиции со счёта (только песочница)."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.trading.models import AccountKind, PendingOperation, TradeRecord

SANDBOX_ONLY_MSG = "Продажа позиций доступна только в песочнице"


def _has_active_trade_record(
    records: list[TradeRecord],
    *,
    figi: str,
    direction: str,
) -> TradeRecord | None:
    for tr in records:
        if tr.figi != figi or tr.direction != direction:
            continue
        if tr.is_active:
            return tr
    return None


def find_sellable_position(portfolio: Portfolio, isin: str) -> PortfolioPosition:
    if not portfolio.is_trading:
        raise ValueError("Портфель не в режиме торговли")
    if portfolio.account_kind != AccountKind.SANDBOX:
        raise ValueError(SANDBOX_ONLY_MSG)

    position = next((p for p in portfolio.positions if p.isin == isin), None)
    if position is None:
        raise ValueError(f"Позиция {isin} не найдена")
    if position.is_closed:
        raise ValueError("Нельзя продать закрытую позицию")
    return position


def validate_sell_request(
    portfolio: Portfolio,
    position: PortfolioPosition,
    lots: int,
) -> int:
    """Проверить запрос на продажу; вернуть доступное число лотов на счёте."""
    if lots <= 0:
        raise ValueError("Invalid lots")

    actual = position.actual_lots if position.actual_lots is not None else 0
    if actual <= 0:
        raise ValueError("На счёте нет лотов для продажи")
    if lots > actual:
        raise ValueError(f"Нельзя продать {lots} лот(а): на счёте только {actual}")

    if position.figi:
        active = _has_active_trade_record(
            portfolio.trade_records,
            figi=position.figi,
            direction="SELL",
        )
        if active is not None:
            raise ValueError("Уже есть активная заявка на продажу этой бумаги")

    return actual


def find_queued_manual_sell(portfolio: Portfolio, isin: str) -> PendingOperation | None:
    for op in portfolio.pending_operations:
        if op.kind == "manual_sell" and op.isin == isin:
            return op
    return None


def queue_manual_sell(
    portfolio: Portfolio,
    position: PortfolioPosition,
    *,
    lots: int,
    price_pct: float,
) -> PendingOperation:
    """Поставить manual_sell в очередь (или обновить существующую для ISIN)."""
    validate_sell_request(portfolio, position, lots)
    actual = position.actual_lots if position.actual_lots is not None else 0
    reason = f"Продажа {lots} лот(а) из {actual} на счёте"

    existing = find_queued_manual_sell(portfolio, position.isin)
    if existing is not None:
        existing.lots = lots
        existing.suggested_price_pct = price_pct
        existing.reason = reason
        if position.figi:
            existing.figi = position.figi
        return existing

    op = PendingOperation(
        kind="manual_sell",
        isin=position.isin,
        name=position.name,
        lots=lots,
        figi=position.figi,
        suggested_price_pct=price_pct,
        reason=reason,
    )
    portfolio.pending_operations.append(op)
    return op


def dismiss_queued_manual_sell(portfolio: Portfolio, op_id: str) -> None:
    """Убрать manual_sell из очереди до отправки на биржу."""
    op = next((item for item in portfolio.pending_operations if item.id == op_id), None)
    if op is None or op.kind != "manual_sell":
        raise ValueError("Продажа в очереди не найдена")

    for tr in portfolio.trade_records:
        if tr.pending_op_id == op_id and tr.is_active:
            raise ValueError("Нельзя убрать — заявка уже на бирже, отмените её")

    portfolio.pending_operations = [
        item for item in portfolio.pending_operations if item.id != op_id
    ]
