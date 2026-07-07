"""Cashflow-события плана и слияние дублирующихся строк timeline."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from bond_monitor.domain.portfolio.models import ReinvestmentSlot, ReinvestmentTriggerReason


@dataclass
class CashflowEvent:
    """Атомарное событие денежного потока в плане портфеля.

    Знак ``amount_rub``:
        * положительный → приток денег в кэш-баланс (купон, погашение, оферта);
        * отрицательный → отток (покупка бумаги).

    ``is_projected = True`` означает, что событие лежит в будущем и
    основано на текущих рыночных параметрах; история (если в портфеле есть
    позиции, купленные в прошлом) идёт с ``is_projected = False``.
    """

    date: date
    kind: str
    amount_rub: float
    description: str
    related_isin: str | None = None
    is_projected: bool = True
    position_id: int | None = None
    lots: int | None = None
    bonds_count: int | None = None


def event_sort_key(event: CashflowEvent) -> tuple[date, int]:
    """Сортировка событий: внутри одной даты сначала покупки, потом купоны/погашения."""
    order = {"purchase": 0, "coupon": 1, "maturity": 2, "put_offer": 2}
    return (event.date, order.get(event.kind, 3))


def _format_bonds_count_suffix(bonds_count: int | None) -> str:
    if bonds_count is None or bonds_count <= 0:
        return ""
    return f" ({bonds_count} шт.)"


def cashflow_event_description(
    kind: str,
    name: str,
    *,
    bonds_count: int | None,
    lots: int | None = None,
    price_suffix: str = "",
) -> str:
    suffix = _format_bonds_count_suffix(bonds_count)
    if kind == "purchase":
        return f"Покупка {lots} лот(а) — {name}{suffix}"
    if kind == "coupon":
        return f"Купон по {name}{suffix}"
    if kind == "put_offer":
        return f"Пут-оферта по {name}{price_suffix}{suffix}"
    return f"Погашение {name}{suffix}"


def _bond_name_from_cashflow_description(description: str) -> str:
    text = description
    if text.endswith(" шт.)"):
        text = text.rsplit(" (", 1)[0]
    if " — " in text:
        return text.split(" — ", 1)[1]
    for prefix in ("Купон по ", "Погашение ", "Пут-оферта по "):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


_MERGEABLE_EVENT_KINDS = frozenset({"coupon", "maturity", "put_offer", "purchase"})


def _refresh_merged_cashflow_description(event: CashflowEvent) -> None:
    """Пересобрать описание после слияния событий с суммированным количеством."""
    if not event.related_isin:
        return
    name = _bond_name_from_cashflow_description(event.description)
    if event.kind == "purchase":
        event.description = cashflow_event_description(
            "purchase",
            name,
            bonds_count=event.bonds_count,
            lots=event.lots,
        )
        return
    price_suffix = ""
    if event.kind == "put_offer" and " (" in event.description:
        tail = event.description.split(" (", 1)[1]
        if "% номинала)" in tail:
            price_suffix = f" ({tail.split(')')[0]})"
    event.description = cashflow_event_description(
        event.kind,
        name,
        bonds_count=event.bonds_count,
        price_suffix=price_suffix,
    )


def merge_cashflow_events(events: list[CashflowEvent]) -> list[CashflowEvent]:
    """Объединить события одной бумаги в один день в одну строку cashflow.

    Несколько позиций (initial + phantom-ы реинвестиций) с одним ISIN
    эмитят отдельные купоны/погашения/покупки на одну дату — для UI
    суммируем их в одно событие.
    """
    sorted_input = sorted(events, key=event_sort_key)
    merged: dict[tuple[date, str, str], CashflowEvent] = {}
    merge_order: list[tuple[date, str, str]] = []
    passthrough: list[CashflowEvent] = []

    for event in sorted_input:
        if event.kind not in _MERGEABLE_EVENT_KINDS or not event.related_isin:
            passthrough.append(event)
            continue
        key = (event.date, event.kind, event.related_isin)
        existing = merged.get(key)
        if existing is None:
            merged[key] = CashflowEvent(
                date=event.date,
                kind=event.kind,
                amount_rub=event.amount_rub,
                description=event.description,
                related_isin=event.related_isin,
                is_projected=event.is_projected,
                lots=event.lots,
                bonds_count=event.bonds_count,
            )
            merge_order.append(key)
            continue
        existing.amount_rub += event.amount_rub
        existing.is_projected = existing.is_projected or event.is_projected
        if event.lots is not None:
            existing.lots = (existing.lots or 0) + event.lots
        if event.bonds_count is not None:
            existing.bonds_count = (existing.bonds_count or 0) + event.bonds_count
        _refresh_merged_cashflow_description(existing)

    result = [merged[key] for key in merge_order] + passthrough
    result.sort(key=event_sort_key)
    return result


def _slot_sort_key(slot: ReinvestmentSlot) -> tuple[date, int, str]:
    """Сортировка слотов реинвестиции по дате наступления события."""
    reason_order = {
        ReinvestmentTriggerReason.MATURITY: 0,
        ReinvestmentTriggerReason.PUT_OFFER: 1,
        ReinvestmentTriggerReason.COUPON_CASH: 2,
    }
    return (
        slot.trigger_date,
        reason_order.get(slot.trigger_reason, 3),
        slot.source_position_isin or slot.effective_isin or "",
    )


def _slot_merge_key(slot: ReinvestmentSlot) -> tuple[date, str, str] | tuple[date, str] | None:
    if slot.trigger_reason == ReinvestmentTriggerReason.COUPON_CASH:
        return (slot.trigger_date, slot.trigger_reason.value)
    if slot.source_position_isin:
        return (slot.trigger_date, slot.trigger_reason.value, slot.source_position_isin)
    return None


def _slot_coalesce_key(slot: ReinvestmentSlot) -> tuple[date, str] | None:
    effective_isin = slot.effective_isin
    if not effective_isin:
        return None
    return (slot.purchase_date, effective_isin)


_SLOT_REASON_PRIORITY = {
    ReinvestmentTriggerReason.MATURITY: 0,
    ReinvestmentTriggerReason.PUT_OFFER: 1,
    ReinvestmentTriggerReason.COUPON_CASH: 2,
}


def _copy_reinvestment_slot(slot: ReinvestmentSlot) -> ReinvestmentSlot:
    return ReinvestmentSlot(
        trigger_date=slot.trigger_date,
        trigger_reason=slot.trigger_reason,
        expected_cash_rub=slot.expected_cash_rub,
        suggested_isin=slot.suggested_isin,
        suggested_name=slot.suggested_name,
        confirmed_isin=slot.confirmed_isin,
        gap_days=slot.gap_days,
        source_position_isin=slot.source_position_isin,
    )


def _accumulate_reinvestment_slot(existing: ReinvestmentSlot, slot: ReinvestmentSlot) -> None:
    existing.expected_cash_rub += slot.expected_cash_rub
    if existing.confirmed_isin is None and slot.confirmed_isin is not None:
        existing.confirmed_isin = slot.confirmed_isin
    if existing.suggested_isin is None and slot.suggested_isin is not None:
        existing.suggested_isin = slot.suggested_isin
    if existing.suggested_name is None and slot.suggested_name is not None:
        existing.suggested_name = slot.suggested_name

    existing_priority = _SLOT_REASON_PRIORITY.get(existing.trigger_reason, 99)
    slot_priority = _SLOT_REASON_PRIORITY.get(slot.trigger_reason, 99)
    if slot_priority < existing_priority:
        existing.trigger_reason = slot.trigger_reason
        existing.trigger_date = slot.trigger_date
        if slot.source_position_isin is not None:
            existing.source_position_isin = slot.source_position_isin
    else:
        existing.trigger_date = min(existing.trigger_date, slot.trigger_date)
        if existing.source_position_isin is None and slot.source_position_isin is not None:
            existing.source_position_isin = slot.source_position_isin


def _merge_reinvestment_slot_groups(
    slots: Sequence[ReinvestmentSlot],
    *,
    key_fn: Callable[[ReinvestmentSlot], tuple | None],
) -> list[ReinvestmentSlot]:
    sorted_input = sorted(slots, key=_slot_sort_key)
    merged: dict[tuple, ReinvestmentSlot] = {}
    merge_order: list[tuple] = []
    passthrough: list[ReinvestmentSlot] = []

    for slot in sorted_input:
        key = key_fn(slot)
        if key is None:
            passthrough.append(slot)
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = _copy_reinvestment_slot(slot)
            merge_order.append(key)
            continue
        _accumulate_reinvestment_slot(existing, slot)

    result = [merged[key] for key in merge_order] + passthrough
    result.sort(key=_slot_sort_key)
    return result


def merge_reinvestment_slots(slots: list[ReinvestmentSlot]) -> list[ReinvestmentSlot]:
    """Объединить дублирующиеся слоты реинвестиции в одну карточку UI.

    Два прохода:

    1. Одинаковые ``trigger_date`` + ``trigger_reason`` + ``source_position_isin``
       (или ``coupon_cash`` на одну дату) — суммируем phantom-позиции одной бумаги.
    2. Одинаковые ``purchase_date`` + ``effective_isin`` — погашение и купонный
       кэш, которые реинвестируются в одну бумагу в один день, показываем одной
       карточкой.
    """
    by_source = _merge_reinvestment_slot_groups(slots, key_fn=_slot_merge_key)
    return _merge_reinvestment_slot_groups(by_source, key_fn=_slot_coalesce_key)
