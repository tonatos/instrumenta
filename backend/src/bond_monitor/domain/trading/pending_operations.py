"""
Генерация и дедупликация ожидающих операций (`PendingOperation`).

Идея: при каждом ререндере UI в режиме торговли вызывается
:func:`compute_pending_operations`, который собирает актуальный список
TODO для пользователя:

* ``initial_buy`` — позиции с ``actual_lots < lots`` (стартовые покупки,
  которые ещё не выполнены или выполнены частично);
* ``reinvest_buy`` — слоты реинвестиции, у которых ``trigger_date ≤ today``
  и нет закрытого `TradeRecord`;
* ``put_offer_submit`` — позиции с ``PutOfferDecision.PENDING`` и открытым
  окном подачи (≤ `PUT_OFFER_REMINDER_DAYS` дней);
* ``manual_sell`` — сохранённые ранее в портфеле (создаются пользователем
  явно через UI кнопку «Поставить SELL»);
* ``top_up_buy`` — сохранённые ранее (создаются батчем после
  подтверждения top-up распределения).

Дедупликация:

* Уже сохранённые в `Portfolio.pending_operations` `manual_sell` и
  `top_up_buy` (явные пользовательские) выводятся как есть, проверяя
  только статус связанной заявки.
* Вычисляемые на лету (`initial_buy`, `reinvest_buy`, `put_offer_submit`):
  если есть `TradeRecord` со статусом ``FILL`` для соответствующего
  (figi, lots) — pending не генерируется. Если есть активный `TradeRecord`
  (`is_active`), pending показывается с пометкой «заявка отправлена,
  ожидает исполнения``.

Идемпотентность обеспечивается стабильными `id` — для
`initial_buy` / `reinvest_buy` / `put_offer_submit` `id` строится
детерминированно из (portfolio.id, kind, isin/slot_source). Это даёт
стабильность query-params (`?pending_confirm=<id>`) между rerun-ами.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    PutOfferDecision,
    ReinvestmentSlot,
)
from bond_monitor.domain.trading.models import PendingOperation, TradeRecord
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, order_amount_rub
from bond_monitor.domain.shared.formatting import format_date
from bond_monitor.domain.trading.policies import (
    buy_limit_price_buffer,
    format_buy_limit_buffer_label,
    suggested_buy_limit_price_pct,
)
from bond_monitor.domain.portfolio.put_offer import put_offer_submit_due
from bond_monitor.domain.trading.ids import stable_id
from bond_monitor.domain.trading.ports import BrokerSnapshot

logger = logging.getLogger(__name__)

PUT_OFFER_SUBMIT_URGENT_DAYS: int = 2
REINVEST_OVERDUE_DAYS: int = 3

_KIND_SORT_ORDER: dict[str, int] = {
    "put_offer_submit": 0,
    "reinvest_buy": 1,
    "initial_buy": 2,
    "top_up_buy": 3,
    "manual_sell": 4,
}

_URGENCY_SORT_ORDER: dict[str, int] = {
    "critical": 0,
    "soon": 1,
    "normal": 2,
}


def _has_fulfilled_trade_record(
    records: list[TradeRecord],
    *,
    figi: str,
    direction: str,
    lots_needed: int,
) -> bool:
    """Есть ли FILL-запись с накопленной суммой лотов ≥ `lots_needed`."""
    fulfilled = 0
    for tr in records:
        if tr.figi != figi or tr.direction != direction:
            continue
        if tr.status == "EXECUTION_REPORT_STATUS_FILL":
            fulfilled += tr.lots_executed or tr.lots
    return fulfilled >= lots_needed


def _is_pending_op_fulfilled(op: PendingOperation, records: list[TradeRecord]) -> bool:
    """Закрыта ли конкретная persisted-операция (top_up_buy / manual_sell).

    Сопоставление только по ``pending_op_id`` — сумма всех FILL по figi
    не используется, иначе стартовая покупка ошибочно закрывает top-up.
    """
    direction = _order_direction(op)
    fulfilled = 0
    for tr in records:
        if tr.pending_op_id != op.id:
            continue
        if tr.direction != direction:
            continue
        if tr.status == "EXECUTION_REPORT_STATUS_FILL":
            fulfilled += tr.lots_executed or tr.lots
    return fulfilled >= op.lots


def _has_active_trade_record(
    records: list[TradeRecord],
    *,
    figi: str,
    direction: str,
) -> TradeRecord | None:
    """Вернуть активную (не FILL/CANCELLED/REJECTED) заявку, если есть."""
    for tr in records:
        if tr.figi != figi or tr.direction != direction:
            continue
        if tr.is_active:
            return tr
    return None


def _find_active_for_op(portfolio: Portfolio, op: PendingOperation) -> TradeRecord | None:
    """Найти активную заявку по pending_op_id или figi+direction."""
    direction = "SELL" if op.kind == "manual_sell" else "BUY"
    for tr in portfolio.trade_records:
        if tr.pending_op_id == op.id and tr.is_active:
            return tr
    if op.figi:
        return _has_active_trade_record(portfolio.trade_records, figi=op.figi, direction=direction)
    return None


def _order_direction(op: PendingOperation) -> str:
    return "SELL" if op.kind == "manual_sell" else "BUY"


def _suggested_buy_price_pct(
    position: PortfolioPosition,
    *,
    snapshot: BrokerSnapshot,
    last_price_pct: PriceUnitPct | None,
    buffer: float,
) -> PriceUnitPct:
    base: float = position.purchase_clean_price_pct
    if position.figi:
        broker_pos = snapshot.bond_positions.get(position.figi)
        if broker_pos is not None and broker_pos.current_price_pct is not None:
            base = float(broker_pos.current_price_pct)
        elif last_price_pct is not None:
            base = float(last_price_pct)
    return suggested_buy_limit_price_pct(base, buffer)


def _suggested_buy_price_from_bond(
    bond: BondRecord,
    *,
    last_price_pct: PriceUnitPct | None,
    buffer: float,
) -> PriceUnitPct | None:
    if last_price_pct is not None:
        return suggested_buy_limit_price_pct(float(last_price_pct), buffer)
    if bond.last_price is not None and bond.last_price > 0:
        return suggested_buy_limit_price_pct(bond.last_price, buffer)
    return None


def _estimate_amount_rub(
    lots: int,
    price_pct: float | None,
    *,
    face_value: float,
    lot_size: int,
    aci_rub_per_bond: float = 0.0,
) -> float | None:
    if lots <= 0 or price_pct is None:
        return None
    return round(
        float(
            order_amount_rub(
                price_pct=PriceUnitPct(price_pct),
                face_value=face_value,
                lot_size=lot_size,
                lots=Lots(lots),
                aci_rub=aci_rub_per_bond,
            )
        ),
        2,
    )


def _resolve_aci_rub_per_bond(
    *,
    bond: BondRecord | None,
    position: PortfolioPosition | None,
    snapshot: BrokerSnapshot,
    figi: str | None,
) -> float:
    """НКД на одну облигацию: MOEX → брокерский snapshot → позиция портфеля."""
    if bond is not None and bond.accrued_interest:
        return float(bond.accrued_interest)
    if figi:
        broker_pos = snapshot.bond_positions.get(figi)
        if broker_pos is not None and broker_pos.current_nkd_rub is not None:
            return float(broker_pos.current_nkd_rub)
    if position is not None:
        return float(position.purchase_aci_rub or 0.0)
    return 0.0


def _enrich_operation(
    op: PendingOperation,
    portfolio: Portfolio,
    today: date,
    universe_by_isin: dict[str, BondRecord],
    snapshot: BrokerSnapshot,
) -> None:
    """Заполнить status, urgency, block_reason и пр. для UI."""
    bond = universe_by_isin.get(op.isin)
    position = next((pos for pos in portfolio.positions if pos.isin == op.isin), None)
    face_value = bond.face_value if bond else (position.face_value if position else 1000.0)
    lot_size = bond.lot_size if bond else (position.lot_size if position else 1)
    aci_rub_per_bond = _resolve_aci_rub_per_bond(
        bond=bond,
        position=position,
        snapshot=snapshot,
        figi=op.figi,
    )

    op.face_value_rub = face_value
    op.lot_size = lot_size
    op.aci_rub_per_bond = aci_rub_per_bond

    if op.suggested_price_pct is not None:
        op.estimated_amount_rub = _estimate_amount_rub(
            op.lots,
            float(op.suggested_price_pct),
            face_value=face_value,
            lot_size=lot_size,
            aci_rub_per_bond=aci_rub_per_bond,
        )

    active = _find_active_for_op(portfolio, op)
    if active is not None:
        op.status = "in_progress"
        op.active_order_id = active.order_id
        op.active_order_status = active.status
        op.submitted_request_uid = active.request_uid
        op.active_order_lots = active.lots
        op.active_order_price_pct = active.price_pct
        op.active_order_total_rub = active.total_order_amount_rub
        op.active_order_commission_rub = active.initial_commission_rub
        op.active_order_lots_executed = active.lots_executed
        op.active_order_bonds_count = active.lots * lot_size if active.lots > 0 else None
        op.urgency = "normal"
        return

    block_reason: str | None = None
    if op.kind in ("initial_buy", "reinvest_buy", "top_up_buy", "manual_sell"):
        if not op.figi:
            block_reason = "Не удалось определить FIGI — обновите счёт или проверьте ISIN"
        elif op.lots <= 0:
            block_reason = "Нет лотов для покупки"
        elif op.suggested_price_pct is None:
            block_reason = "Нет рыночной цены для расчёта лимитной заявки"
    if block_reason:
        op.status = "blocked"
        op.block_reason = block_reason
        op.urgency = "normal"
        return

    overdue = False
    if op.kind == "reinvest_buy" and op.due_date is not None:
        days_past = (today - op.due_date).days
        if days_past > REINVEST_OVERDUE_DAYS:
            overdue = True
    if op.kind == "put_offer_submit" and op.due_date is not None:
        days_left = (op.due_date - today).days
        if days_left < 0:
            overdue = True
        elif days_left <= PUT_OFFER_SUBMIT_URGENT_DAYS:
            op.urgency = "critical"
            _append_put_offer_submission_reminder(op, days_left=days_left)
        elif days_left <= 7:
            op.urgency = "soon"

    if overdue:
        op.status = "overdue"
        op.urgency = "critical"
    else:
        op.status = "action_required"
        if op.kind == "put_offer_submit" and op.urgency == "normal":
            if op.due_date and (op.due_date - today).days <= 7:
                op.urgency = "soon"

    if op.kind == "put_offer_submit":
        for pos in portfolio.positions:
            if pos.isin == op.isin:
                op.chat_template = render_put_offer_chat_template(pos)
                break


def _sort_key(op: PendingOperation) -> tuple[int, int, date, str]:
    return (
        _URGENCY_SORT_ORDER.get(op.urgency, 2),
        _KIND_SORT_ORDER.get(op.kind, 9),
        op.due_date or date.max,
        op.id,
    )


def _enrich_and_sort(
    ops: list[PendingOperation],
    portfolio: Portfolio,
    today: date,
    universe_by_isin: dict[str, BondRecord],
    snapshot: BrokerSnapshot,
) -> list[PendingOperation]:
    for op in ops:
        _enrich_operation(op, portfolio, today, universe_by_isin, snapshot)
    ops.sort(key=_sort_key)
    return ops


def pending_top_up_lots_for_isin(portfolio: Portfolio, isin: str) -> int:
    """Лоты, уже покрытые сохранёнными top_up_buy pending operations."""
    total = 0
    for op in portfolio.pending_operations:
        if op.kind != "top_up_buy" or op.isin != isin:
            continue
        if _is_pending_op_fulfilled(op, portfolio.trade_records):
            continue
        total += op.lots
    return total


def _effective_figi(
    isin: str,
    position_figi: str | None,
    universe_by_isin: dict[str, BondRecord],
) -> str | None:
    """FIGI для заявки: enriched universe приоритетнее устаревшего figi в позиции."""
    bond = universe_by_isin.get(isin)
    if bond and bond.figi:
        return bond.figi
    return position_figi or None


def _is_api_tradable_bond(
    portfolio: Portfolio,
    isin: str,
    universe_by_isin: dict[str, BondRecord],
) -> bool:
    """Можно ли выставлять BUY через T-Invest API для этой бумаги."""
    if not portfolio.api_trade_only:
        return True
    bond = universe_by_isin.get(isin)
    if bond is None:
        # Нет данных в universe — не режем очередь; ensure_order_instrument при confirm.
        return True
    return bond.api_trade_available_flag is True


def _gen_initial_buys(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    last_prices: dict[str, PriceUnitPct] | None,
    *,
    universe_by_isin: dict[str, BondRecord],
) -> list[PendingOperation]:
    result: list[PendingOperation] = []
    last_prices = last_prices or {}
    buffer = buy_limit_price_buffer(portfolio.account_kind)
    buffer_label = format_buy_limit_buffer_label(buffer)
    for position in portfolio.positions:
        if not _is_api_tradable_bond(portfolio, position.isin, universe_by_isin):
            continue
        figi = _effective_figi(position.isin, position.figi, universe_by_isin)
        actual = position.actual_lots if position.actual_lots is not None else 0
        if actual >= position.lots:
            continue
        remaining = position.lots - actual - pending_top_up_lots_for_isin(portfolio, position.isin)
        if remaining <= 0:
            continue
        active = (
            _has_active_trade_record(portfolio.trade_records, figi=figi, direction="BUY")
            if figi
            else None
        )
        last_price = last_prices.get(figi or "")
        suggested = (
            _suggested_buy_price_pct(
                position,
                snapshot=snapshot,
                last_price_pct=last_price,
                buffer=buffer,
            )
            if figi
            else None
        )
        result.append(
            PendingOperation(
                id=stable_id(portfolio.id, "initial_buy", position.isin),
                kind="initial_buy",
                isin=position.isin,
                name=position.name,
                lots=remaining,
                figi=figi,
                suggested_price_pct=float(suggested) if suggested is not None else None,
                due_date=None,
                reason=(
                    f"Стартовая покупка: {remaining} лот(а) из {position.lots}"
                    + (f" (в обработке: заявка {active.order_id[:8]}…)" if active else "")
                    + (
                        ""
                        if active
                        else f". Лимит ≈ рынок +{buffer_label} — пассивная заявка, "
                        "исполнение не гарантировано"
                    )
                ),
                submitted_request_uid=active.request_uid if active else None,
            )
        )
    return result


def _gen_reinvest_buys(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    last_prices: dict[str, PriceUnitPct] | None,
    today: date,
    *,
    resolved_slots: Sequence[ReinvestmentSlot] | None,
    universe_by_isin: dict[str, BondRecord],
) -> list[PendingOperation]:
    result: list[PendingOperation] = []
    last_prices = last_prices or {}
    buffer = buy_limit_price_buffer(portfolio.account_kind)
    slots = list(resolved_slots) if resolved_slots is not None else list(portfolio.slots)
    for slot in slots:
        if slot.trigger_date > today:
            continue
        target_isin = slot.effective_isin
        if not target_isin:
            continue
        if not _is_api_tradable_bond(portfolio, target_isin, universe_by_isin):
            continue
        bond = universe_by_isin.get(target_isin)
        figi = _effective_figi(
            target_isin,
            next((pos.figi for pos in portfolio.positions if pos.isin == target_isin), None),
            universe_by_isin,
        )
        lots = 1
        if bond and bond.price_per_lot_rub and bond.price_per_lot_rub > 0:
            lots = int(slot.expected_cash_rub // bond.price_per_lot_rub)
        if (
            figi
            and lots > 0
            and _has_fulfilled_trade_record(
                portfolio.trade_records,
                figi=figi,
                direction="BUY",
                lots_needed=lots,
            )
        ):
            continue
        last_price = last_prices.get(figi or "")
        suggested_pct: PriceUnitPct | None = None
        if bond:
            suggested_pct = _suggested_buy_price_from_bond(
                bond, last_price_pct=last_price, buffer=buffer
            )
        if suggested_pct is None:
            for pos in portfolio.positions:
                if pos.isin == target_isin:
                    suggested_pct = suggested_buy_limit_price_pct(
                        pos.purchase_clean_price_pct, buffer
                    )
                    break
        name = bond.name if bond else f"Реинвест слота {format_date(slot.trigger_date)}"
        result.append(
            PendingOperation(
                id=stable_id(
                    portfolio.id, "reinvest_buy", target_isin + slot.trigger_date.isoformat()
                ),
                kind="reinvest_buy",
                isin=target_isin,
                name=name,
                lots=max(lots, 0),
                figi=figi,
                suggested_price_pct=float(suggested_pct) if suggested_pct is not None else None,
                due_date=slot.trigger_date,
                reason=(
                    f"Слот реинвестиции по {slot.trigger_reason.value} от "
                    f"{format_date(slot.trigger_date)}: ожидается "
                    f"{slot.expected_cash_rub:,.0f} ₽"
                ),
                slot_id=stable_id(
                    portfolio.id, "reinvest_slot", target_isin + slot.trigger_date.isoformat()
                ),
            )
        )
    return result


def _append_put_offer_submission_reminder(op: PendingOperation, *, days_left: int) -> None:
    """Добавить явное напоминание предъявить бумаги в последние дни окна подачи."""
    if "предъявите бумаги" in op.reason.lower():
        return
    due_str = format_date(op.due_date)
    if days_left == 0:
        deadline_hint = f"сегодня ({due_str})"
    elif days_left == 1:
        deadline_hint = f"завтра ({due_str})"
    else:
        deadline_hint = f"до {due_str} включительно"
    op.reason = (
        f"{op.reason} Срочно: предъявите бумаги {deadline_hint}, "
        f"если ещё не подали заявку."
    )


def _gen_put_offer_submits(
    portfolio: Portfolio,
    today: date,
) -> list[PendingOperation]:
    result: list[PendingOperation] = []
    for position in portfolio.positions:
        if position.put_offer_decision != PutOfferDecision.PENDING:
            continue
        if not put_offer_submit_due(position, today):
            continue
        result.append(
            PendingOperation(
                id=stable_id(portfolio.id, "put_offer_submit", position.isin),
                kind="put_offer_submit",
                isin=position.isin,
                name=position.name,
                lots=position.lots,
                figi=position.figi,
                suggested_price_pct=(
                    PriceUnitPct(position.offer_price_pct)
                    if position.offer_price_pct is not None
                    else None
                ),
                due_date=(position.offer_submission_end or position.offer_date),
                reason=(
                    f"Пут-оферта {format_date(position.offer_date)}"
                    + (
                        f" по цене {position.offer_price_pct:.2f}%"
                        if position.offer_price_pct is not None
                        else ""
                    )
                    + ". Подайте заявку через чат брокера (API не умеет)."
                ),
            )
        )
    return result


def _filter_persisted_pending(
    portfolio: Portfolio,
    *,
    universe_by_isin: dict[str, BondRecord] | None = None,
) -> list[PendingOperation]:
    universe_by_isin = universe_by_isin or {}
    result: list[PendingOperation] = []
    for op in portfolio.pending_operations:
        if op.kind not in ("manual_sell", "top_up_buy"):
            continue
        if not _is_api_tradable_bond(portfolio, op.isin, universe_by_isin):
            continue
        figi = _effective_figi(op.isin, op.figi, universe_by_isin)
        direction = _order_direction(op)
        if _is_pending_op_fulfilled(op, portfolio.trade_records):
            continue
        if figi and figi != op.figi:
            op = replace(op, figi=figi)
        result.append(op)
    return result


def compute_pending_operations(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    today: date,
    *,
    last_prices: dict[str, PriceUnitPct] | None = None,
    universe: Sequence[BondRecord] | None = None,
    resolved_slots: Sequence[ReinvestmentSlot] | None = None,
) -> list[PendingOperation]:
    """Собрать актуальный список ожидающих операций для UI."""
    if not portfolio.is_trading:
        return []

    universe_by_isin: dict[str, BondRecord] = (
        {b.isin: b for b in universe} if universe is not None else {}
    )

    result: list[PendingOperation] = []
    result.extend(
        _gen_initial_buys(
            portfolio,
            snapshot,
            last_prices,
            universe_by_isin=universe_by_isin,
        )
    )
    result.extend(
        _gen_reinvest_buys(
            portfolio,
            snapshot,
            last_prices,
            today,
            resolved_slots=resolved_slots,
            universe_by_isin=universe_by_isin,
        )
    )
    result.extend(_gen_put_offer_submits(portfolio, today))
    result.extend(_filter_persisted_pending(portfolio, universe_by_isin=universe_by_isin))
    return _enrich_and_sort(result, portfolio, today, universe_by_isin, snapshot)


def sweep_non_api_tradable_pending(
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> int:
    """Удалить сохранённые top_up_buy/manual_sell для не-API бумаг при api_trade_only."""
    if not portfolio.api_trade_only or not portfolio.pending_operations:
        return 0
    keep: list[PendingOperation] = []
    removed = 0
    for op in portfolio.pending_operations:
        if op.kind in ("manual_sell", "top_up_buy") and not _is_api_tradable_bond(
            portfolio, op.isin, universe_by_isin
        ):
            removed += 1
            continue
        keep.append(op)
    portfolio.pending_operations = keep
    return removed


def api_trade_position_warnings(
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> list[str]:
    """Позиции плана, которые нельзя купить через API при включённом фильтре."""
    if not portfolio.api_trade_only:
        return []
    warnings: list[str] = []
    for pos in portfolio.positions:
        if _is_api_tradable_bond(portfolio, pos.isin, universe_by_isin):
            continue
        warnings.append(
            f"{pos.name} ({pos.isin}): не торгуется через T-Invest API — "
            f"удалите позицию или пересоберите портфель (автосбор)"
        )
    return warnings


def sweep_completed_pending(portfolio: Portfolio) -> int:
    """Удалить из `portfolio.pending_operations` закрытые manual_sell/top_up_buy."""
    if not portfolio.pending_operations:
        return 0
    keep: list[PendingOperation] = []
    for op in portfolio.pending_operations:
        if op.kind not in ("manual_sell", "top_up_buy"):
            keep.append(op)
            continue
        direction = _order_direction(op)
        if _is_pending_op_fulfilled(op, portfolio.trade_records):
            continue
        keep.append(op)
    removed = len(portfolio.pending_operations) - len(keep)
    portfolio.pending_operations = keep
    return removed


def render_put_offer_chat_template(position: PortfolioPosition) -> str:
    """Готовый текст для копирования в чат брокера — подача пут-оферты."""
    offer_date = format_date(position.offer_date)
    submission_end = (
        f" (срок подачи до {format_date(position.offer_submission_end)})"
        if position.offer_submission_end
        else ""
    )
    return (
        f"Здравствуйте! Прошу подать поручение на досрочный выкуп облигаций "
        f"по пут-оферте.\n\n"
        f"Облигация: {position.name}\n"
        f"ISIN: {position.isin}\n"
        f"Количество облигаций: {position.bonds_count} шт ({position.lots} лот по {position.lot_size})\n"
        f"Дата оферты: {offer_date}{submission_end}\n\n"
        f"Спасибо!"
    )


from bond_monitor.domain.portfolio.put_offer import PUT_OFFER_REMINDER_DAYS

__all__ = [
    "PUT_OFFER_REMINDER_DAYS",
    "PUT_OFFER_SUBMIT_URGENT_DAYS",
    "REINVEST_OVERDUE_DAYS",
    "compute_pending_operations",
    "render_put_offer_chat_template",
    "sweep_completed_pending",
]
