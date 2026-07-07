"""Жизненный цикл позиций портфеля в режиме торговли."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
)
from bond_monitor.domain.trading.models import PendingOperation
from bond_monitor.domain.portfolio.position_factory import position_from_bond
from bond_monitor.domain.trading.ids import stable_id
from bond_monitor.domain.trading.ports import BrokerSnapshot

_FILL_STATUS = "EXECUTION_REPORT_STATUS_FILL"


def position_was_ever_held(portfolio: Portfolio, position: PortfolioPosition) -> bool:
    """Была ли позиция когда-либо куплена (по FILL-записям)."""
    if not position.figi:
        return False
    for tr in portfolio.trade_records:
        if (
            tr.figi == position.figi
            and tr.direction == "BUY"
            and tr.status == _FILL_STATUS
            and (tr.lots_executed or tr.lots) > 0
        ):
            return True
    return False


def _position_exit_date(position: PortfolioPosition) -> date | None:
    if (
        position.put_offer_decision == PutOfferDecision.EXERCISE
        and position.offer_date is not None
    ):
        return position.offer_date
    return position.maturity_date


def _reinvest_source_from_slot(slot: ReinvestmentSlot) -> PositionSourceType:
    if slot.trigger_reason == ReinvestmentTriggerReason.PUT_OFFER:
        return PositionSourceType.REINVEST_PUT_OFFER
    return PositionSourceType.REINVEST_MATURITY


def _reinvest_op_id(portfolio: Portfolio, slot: ReinvestmentSlot, target_isin: str) -> str:
    return stable_id(
        portfolio.id,
        "reinvest_buy",
        target_isin + slot.trigger_date.isoformat(),
    )


def _open_position_for_isin(
    portfolio: Portfolio,
    isin: str,
) -> PortfolioPosition | None:
    for position in portfolio.positions:
        if position.isin == isin and not position.is_closed:
            return position
    return None


def reinvest_source_for_slot(slot: ReinvestmentSlot) -> PositionSourceType:
    """Источник позиции по типу триггера слота реинвестиции."""
    return _reinvest_source_from_slot(slot)


def find_reinvest_slot_for_op(
    portfolio: Portfolio,
    slots: Sequence[ReinvestmentSlot],
    op: PendingOperation,
) -> ReinvestmentSlot | None:
    """Найти слот реинвестиции по ``slot_id`` pending-операции."""
    if not op.slot_id:
        return None
    for slot in slots:
        target_isin = slot.confirmed_isin or slot.suggested_isin
        if not target_isin:
            continue
        slot_id = stable_id(
            portfolio.id,
            "reinvest_slot",
            target_isin + slot.trigger_date.isoformat(),
        )
        if slot_id == op.slot_id:
            return slot
    return None


def ensure_reinvest_position(
    portfolio: Portfolio,
    bond: BondRecord,
    *,
    lots: int,
    source: PositionSourceType,
    figi: str | None,
    today: date,
    purchase_price_pct: float,
) -> PortfolioPosition:
    """Запланировать позицию реинвестиции до отправки заявки (как top-up)."""
    if lots <= 0:
        raise ValueError("lots must be positive")

    position = _open_position_for_isin(portfolio, bond.isin)
    if position is None:
        position = position_from_bond(
            bond,
            lots=lots,
            purchase_date=today,
            source=source,
        )
        position.figi = figi
        if purchase_price_pct > 0:
            position.purchase_clean_price_pct = purchase_price_pct
        portfolio.positions.append(position)
        return position

    position.lots += lots
    if figi and not position.figi:
        position.figi = figi
    return position


def close_matured_positions(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    today: date,
) -> int:
    """Архивировать позиции, погашённые/выкупленные и отсутствующие на счёте."""
    if not portfolio.is_trading:
        return 0

    closed = 0
    for position in portfolio.positions:
        if position.is_closed or not position.figi:
            continue
        if position.actual_lots != 0:
            continue
        broker_pos = snapshot.bond_positions.get(position.figi)
        if broker_pos is not None and broker_pos.quantity > 0:
            continue
        exit_date = _position_exit_date(position)
        if exit_date is None or exit_date > today:
            continue
        if not position_was_ever_held(portfolio, position):
            continue
        position.closed_at = today
        position.actual_lots = 0
        closed += 1
    return closed


def _slot_for_reinvest_op(
    portfolio: Portfolio,
    op_id: str,
) -> tuple[ReinvestmentSlot, str] | None:
    for slot in portfolio.slots:
        target_isin = slot.confirmed_isin or slot.suggested_isin
        if not target_isin:
            continue
        if _reinvest_op_id(portfolio, slot, target_isin) == op_id:
            return slot, target_isin
    return None


def _reinvest_position_exists(
    portfolio: Portfolio,
    *,
    isin: str,
    lots: int,
    pending_op_id: str,
) -> bool:
    position = _open_position_for_isin(portfolio, isin)
    if position is None:
        return False
    for tr in portfolio.trade_records:
        if tr.pending_op_id == pending_op_id and tr.status == _FILL_STATUS:
            return True
    return position.lots >= lots


def apply_filled_reinvest_buys(
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
    today: date,
) -> int:
    """Создать позиции по FILL reinvest_buy, если confirm не успел записать план."""
    if not portfolio.is_trading:
        return 0

    created = 0
    seen_op_ids: set[str] = set()
    for tr in portfolio.trade_records:
        if tr.direction != "BUY" or tr.status != _FILL_STATUS or not tr.pending_op_id:
            continue
        if tr.pending_op_id in seen_op_ids:
            continue
        seen_op_ids.add(tr.pending_op_id)

        match = _slot_for_reinvest_op(portfolio, tr.pending_op_id)
        if match is None:
            continue
        slot, target_isin = match
        lots = tr.lots_executed or tr.lots
        if lots <= 0:
            continue
        if _reinvest_position_exists(
            portfolio,
            isin=target_isin,
            lots=lots,
            pending_op_id=tr.pending_op_id,
        ):
            continue

        bond = universe_by_isin.get(target_isin)
        if bond is None:
            continue
        ensure_reinvest_position(
            portfolio,
            bond,
            lots=lots,
            source=_reinvest_source_from_slot(slot),
            figi=tr.figi,
            today=today,
            purchase_price_pct=float(tr.price_pct or bond.last_price or 0.0),
        )
        created += 1
    return created


__all__ = [
    "apply_filled_reinvest_buys",
    "close_matured_positions",
    "ensure_reinvest_position",
    "find_reinvest_slot_for_op",
    "position_was_ever_held",
    "reinvest_source_for_slot",
]
