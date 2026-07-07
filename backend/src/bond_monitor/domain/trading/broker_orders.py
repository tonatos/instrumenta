"""Импорт активных заявок со счёта брокера в локальный портфель."""

from __future__ import annotations

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.trading.models import AccountKind, PendingOperation, TradeRecord
from bond_monitor.domain.trading.ports import BrokerActiveOrder
from bond_monitor.domain.trading.sell_position import find_queued_manual_sell


def _position_for_figi(
    portfolio: Portfolio,
    figi: str,
    universe_by_isin: dict[str, BondRecord],
) -> PortfolioPosition | None:
    for pos in portfolio.positions:
        if pos.figi == figi:
            return pos
    for bond in universe_by_isin.values():
        if bond.figi == figi:
            return next((p for p in portfolio.positions if p.isin == bond.isin), None)
    return None


def _resolve_isin_name(
    position: PortfolioPosition | None,
    figi: str,
    universe_by_isin: dict[str, BondRecord],
) -> tuple[str | None, str]:
    if position is not None:
        return position.isin, position.name
    for bond in universe_by_isin.values():
        if bond.figi == figi:
            return bond.isin, bond.name
    return None, figi


def _trade_record_index(
    portfolio: Portfolio,
) -> tuple[dict[str, TradeRecord], dict[str, TradeRecord]]:
    by_order_id: dict[str, TradeRecord] = {}
    by_request_uid: dict[str, TradeRecord] = {}
    for tr in portfolio.trade_records:
        if tr.order_id:
            by_order_id[tr.order_id] = tr
        if tr.request_uid:
            by_request_uid[tr.request_uid] = tr
    return by_order_id, by_request_uid


def _ensure_manual_sell_pending(
    portfolio: Portfolio,
    *,
    position: PortfolioPosition,
    order: BrokerActiveOrder,
    trade_record: TradeRecord,
) -> PendingOperation:
    existing = find_queued_manual_sell(portfolio, position.isin)
    if existing is not None:
        if trade_record.pending_op_id is None:
            trade_record.pending_op_id = existing.id
        if position.figi and not existing.figi:
            existing.figi = position.figi
        if order.price_pct is not None:
            existing.suggested_price_pct = order.price_pct
        return existing

    op = PendingOperation(
        kind="manual_sell",
        isin=position.isin,
        name=position.name,
        lots=order.lots_requested,
        figi=order.figi,
        suggested_price_pct=order.price_pct,
        reason="Заявка на бирже — импорт при синхронизации",
    )
    portfolio.pending_operations.append(op)
    trade_record.pending_op_id = op.id
    return op


def reconcile_active_broker_orders(
    portfolio: Portfolio,
    orders: list[BrokerActiveOrder],
    *,
    universe_by_isin: dict[str, BondRecord],
) -> int:
    """Подтянуть активные заявки со счёта, если их нет в `trade_records`/очереди.

    Возвращает число импортированных или связанных заявок.
    """
    if not portfolio.is_trading or not portfolio.account_id or not portfolio.account_kind:
        return 0

    by_order_id, by_request_uid = _trade_record_index(portfolio)
    imported = 0

    for order in orders:
        if not order.figi:
            continue

        existing = by_order_id.get(order.order_id)
        if existing is None and order.request_uid:
            existing = by_request_uid.get(order.request_uid)

        if existing is not None:
            if not existing.order_id:
                existing.order_id = order.order_id
            if existing.status != order.status:
                existing.status = order.status
            if order.lots_executed != existing.lots_executed:
                existing.lots_executed = order.lots_executed
            if order.total_order_amount_rub is not None:
                existing.total_order_amount_rub = order.total_order_amount_rub
            if order.initial_commission_rub is not None:
                existing.initial_commission_rub = order.initial_commission_rub
            if order.price_pct is not None:
                existing.price_pct = order.price_pct

            if order.direction == "SELL":
                position = _position_for_figi(portfolio, order.figi, universe_by_isin)
                if position is not None:
                    _ensure_manual_sell_pending(
                        portfolio,
                        position=position,
                        order=order,
                        trade_record=existing,
                    )
            continue

        position = _position_for_figi(portfolio, order.figi, universe_by_isin)
        isin, name = _resolve_isin_name(position, order.figi, universe_by_isin)
        if isin is None:
            continue

        request_uid = order.request_uid or f"imported-{order.order_id}"
        trade_record = TradeRecord(
            request_uid=request_uid,
            account_id=portfolio.account_id,
            account_kind=portfolio.account_kind,
            figi=order.figi,
            direction=order.direction,
            lots=order.lots_requested,
            order_id=order.order_id,
            price_pct=order.price_pct,
            status=order.status,
            total_order_amount_rub=order.total_order_amount_rub,
            initial_commission_rub=order.initial_commission_rub,
            lots_executed=order.lots_executed,
        )
        portfolio.trade_records.append(trade_record)
        by_order_id[order.order_id] = trade_record
        if request_uid:
            by_request_uid[request_uid] = trade_record
        imported += 1

        if order.direction == "SELL" and position is not None:
            _ensure_manual_sell_pending(
                portfolio,
                position=position,
                order=order,
                trade_record=trade_record,
            )

    return imported


__all__ = ["reconcile_active_broker_orders"]
