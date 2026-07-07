"""Reinvestment slot selection, validation and override helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.cashflow import _slot_sort_key
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    ReinvestmentSlot,
    ReinvestmentSlotStatus,
    RiskProfile,
)
from bond_monitor.domain.portfolio.plan_models import (
    MIN_REPLACEMENT_HORIZON_DAYS,
    SLOT_CANDIDATES_LIMIT,
)
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    BondSelectionContext,
)
from bond_monitor.domain.portfolio.put_offer import put_offer_buy_blocked
from bond_monitor.domain.portfolio.selection import (
    bond_eligibility_reason,
    explain_selection_failure,
    has_usable_price,
    select_best_bond,
    select_ranked_bonds,
)
from bond_monitor.domain.shared.formatting import format_date


def selection_context(
    *,
    profile: RiskProfile,
    horizon_date: date,
    purchase_date: date,
    api_trade_only: bool,
    budget_rub: float | None = None,
) -> BondSelectionContext:
    return BondSelectionContext(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=purchase_date,
        budget_rub=budget_rub,
        api_trade_only=api_trade_only,
    )


def validate_replacement_bond(
    bond: BondRecord,
    *,
    slot_purchase_date: date,
    horizon: date,
) -> str | None:
    """Проверить, что бумага реально может быть куплена в слот на ``slot_purchase_date``.

    Возвращает None, если всё ок; иначе — короткое описание причины,
    почему бумага непригодна (используется в plan.notes).

    Это критический guard от data-bug-ов, где UI-селект слотов
    показывает бумагу с уже прошедшей датой погашения (см.
    :func:`ui.portfolio._render_single_slot` — там кандидаты беруутся из
    всего профильного универса без фильтра по дате). Если попытаться
    «купить» такую бумагу, планировщик эмитит maturity-событие в
    прошлом → cash приходит ДО списания на покупку → удвоение капитала.
    """
    if bond.maturity_date is None:
        return "у бумаги нет даты погашения"
    if bond.maturity_date <= slot_purchase_date:
        return (
            f"бумага гасится {format_date(bond.maturity_date)}, что НЕ позже "
            f"даты покупки {format_date(slot_purchase_date)}"
        )
    days_remaining = (bond.maturity_date - slot_purchase_date).days
    if days_remaining < MIN_REPLACEMENT_HORIZON_DAYS:
        return (
            f"до погашения {format_date(bond.maturity_date)} осталось "
            f"всего {days_remaining} дн. (< MIN_REPLACEMENT_HORIZON_DAYS = "
            f"{MIN_REPLACEMENT_HORIZON_DAYS})"
        )
    if bond.maturity_date > horizon:
        # Это не блокер: бумага уйдёт за горизонт, превратится в
        # HeldPositionAtHorizon. Но в slot мы её принимать не хотим:
        # реинвест должен иметь чёткую дату возврата в кэш в пределах
        # плана, иначе цепочка обрывается.
        return (
            f"погашение {format_date(bond.maturity_date)} позже горизонта "
            f"{format_date(horizon)} — реинвест прервётся"
        )
    if bond.has_default or bond.has_technical_default:
        return "у бумаги статус дефолта / тех.дефолта"
    blocked = put_offer_buy_blocked(bond, slot_purchase_date)
    if blocked is not None:
        return blocked
    return None


def _slot_candidate_dict(bond: BondRecord) -> dict[str, Any]:
    return {
        "isin": bond.isin,
        "name": bond.name,
        "score": bond.score,
        "ytm_net": bond.ytm_net,
    }


def enrich_reinvestment_slot(
    slot: ReinvestmentSlot,
    *,
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    key_rate: float,
    tax_rate: float,
) -> ReinvestmentSlot:
    """Return a copy of *slot* with plan-response metadata for the UI."""
    universe_by_isin = {b.isin: b for b in universe}
    ctx = selection_context(
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        purchase_date=slot.purchase_date,
        api_trade_only=portfolio.api_trade_only,
        budget_rub=slot.expected_cash_rub,
    )
    ranked = select_ranked_bonds(
        universe,
        ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )
    candidates = [_slot_candidate_dict(b) for b in ranked.bonds[:SLOT_CANDIDATES_LIMIT]]

    status = ReinvestmentSlotStatus.OK
    failure_reason: str | None = None
    target_isin = slot.effective_isin

    if target_isin is None:
        status = ReinvestmentSlotStatus.NO_CANDIDATE
        failure_reason = explain_selection_failure(universe, ctx)
    else:
        target_bond = universe_by_isin.get(target_isin)
        if target_bond is None or not has_usable_price(target_bond):
            status = ReinvestmentSlotStatus.INVALID_SELECTION
            failure_reason = (
                f"бумага {target_isin} отсутствует в актуальном универсе или нет рыночной цены"
            )
        else:
            invalid_reason = validate_replacement_bond(
                target_bond,
                slot_purchase_date=slot.purchase_date,
                horizon=portfolio.horizon_date,
            )
            if invalid_reason is not None:
                status = ReinvestmentSlotStatus.INVALID_SELECTION
                failure_reason = invalid_reason
            else:
                lot_cost = target_bond.price_per_lot_rub or 0.0
                if lot_cost > 0 and slot.expected_cash_rub < lot_cost:
                    status = ReinvestmentSlotStatus.INSUFFICIENT_CASH
                    failure_reason = (
                        f"ожидаемого кэша ({slot.expected_cash_rub:.0f} ₽) не хватает "
                        f"на 1 лот {target_bond.name} ({lot_cost:.0f} ₽)"
                    )

    return ReinvestmentSlot(
        trigger_date=slot.trigger_date,
        trigger_reason=slot.trigger_reason,
        expected_cash_rub=slot.expected_cash_rub,
        suggested_isin=slot.suggested_isin,
        suggested_name=slot.suggested_name,
        confirmed_isin=slot.confirmed_isin,
        gap_days=slot.gap_days,
        source_position_isin=slot.source_position_isin,
        status=status,
        failure_reason=failure_reason,
        eligible_candidates=candidates,
    )


def validate_slot_replacement(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    *,
    slot: ReinvestmentSlot,
    confirmed_isin: str,
    key_rate: float,
    tax_rate: float,
) -> str | None:
    """Validate manual replacement before persisting override."""
    universe_by_isin = {b.isin: b for b in universe}
    bond = universe_by_isin.get(confirmed_isin)
    if bond is None:
        return f"облигация {confirmed_isin} не найдена в универсе MOEX"

    ctx = selection_context(
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        purchase_date=slot.purchase_date,
        api_trade_only=portfolio.api_trade_only,
        budget_rub=slot.expected_cash_rub,
    )
    eligibility = bond_eligibility_reason(
        bond,
        ctx,
        DEFAULT_BOND_SELECTION_POLICY,
        check_budget=True,
    )
    if eligibility is not None:
        return eligibility

    invalid_reason = validate_replacement_bond(
        bond,
        slot_purchase_date=slot.purchase_date,
        horizon=portfolio.horizon_date,
    )
    if invalid_reason is not None:
        return invalid_reason

    lot_cost = bond.price_per_lot_rub or 0.0
    if lot_cost > 0 and slot.expected_cash_rub < lot_cost:
        return (
            f"ожидаемого кэша ({slot.expected_cash_rub:.0f} ₽) не хватает "
            f"на 1 лот ({lot_cost:.0f} ₽)"
        )
    return None


def prune_stale_slot_overrides(
    portfolio: Portfolio,
    resolved_slots: Sequence[ReinvestmentSlot],
) -> bool:
    """Drop persisted slot overrides that no longer belong to the current plan.

    ``portfolio.slots`` stores only user overrides (``confirmed_isin``) keyed by
    ``source_position_isin``. When the planning horizon changes, downstream
    phantom sources may disappear from :func:`build_plan` output — those stale
    entries must be removed so forecast reinvestment chains stay in sync with
    the new horizon without touching factual ``portfolio.positions``.
    """
    active_sources = {
        slot.source_position_isin for slot in resolved_slots if slot.source_position_isin
    }
    before = len(portfolio.slots)
    portfolio.slots = [
        slot for slot in portfolio.slots if slot.source_position_isin in active_sources
    ]
    return len(portfolio.slots) != before


def clear_downstream_slot_overrides(
    portfolio: Portfolio,
    source_position_isin: str,
    resolved_slots: Sequence[ReinvestmentSlot],
) -> bool:
    """Clear manual overrides for slots downstream of *source_position_isin*."""
    ordered = sorted(resolved_slots, key=_slot_sort_key)
    slot_index = next(
        (i for i, slot in enumerate(ordered) if slot.source_position_isin == source_position_isin),
        None,
    )
    if slot_index is None:
        return False

    downstream_sources = {
        slot.source_position_isin for slot in ordered[slot_index + 1 :] if slot.source_position_isin
    }
    changed = False
    for persisted in portfolio.slots:
        if (
            persisted.source_position_isin in downstream_sources
            and persisted.confirmed_isin is not None
        ):
            persisted.confirmed_isin = None
            changed = True
    return changed


def clear_slot_override(portfolio: Portfolio, source_position_isin: str | None) -> bool:
    """Сбросить ``confirmed_isin`` для слота с данной source-позицией (in-memory).

    Возвращает ``True``, если portfolio.slots были изменены.
    Persistence — ответственность application layer.
    """
    if not source_position_isin:
        return False

    changed = False
    for slot in portfolio.slots:
        if slot.source_position_isin == source_position_isin and slot.confirmed_isin is not None:
            slot.confirmed_isin = None
            changed = True
    if changed:
        portfolio.slots = [
            s
            for s in portfolio.slots
            if s.confirmed_isin is not None or s.source_position_isin != source_position_isin
        ]
    return changed


def _explain_replacement_failure(
    universe: Sequence[BondRecord],
    *,
    target_date: date,
    profile: RiskProfile,
    amount: float,
    horizon_date: date,
    api_trade_only: bool = False,
) -> str:
    """Сформировать пояснение, почему подбор замены не нашёл бумагу."""
    ctx = selection_context(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=target_date,
        api_trade_only=api_trade_only,
        budget_rub=amount,
    )
    return explain_selection_failure(universe, ctx)


def select_replacement(
    universe: Sequence[BondRecord],
    *,
    target_date: date,
    profile: RiskProfile,
    amount: float,
    horizon_date: date,
    key_rate: float,
    tax_rate: float,
    api_trade_only: bool = False,
) -> tuple[BondRecord | None, str]:
    """Подобрать бумагу-замену для слота реинвестиции.

    Делегирует отбор и ранжирование в :mod:`domain.portfolio.selection`.
    """
    ctx = selection_context(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=target_date,
        api_trade_only=api_trade_only,
        budget_rub=amount,
    )
    return select_best_bond(
        universe,
        ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )
