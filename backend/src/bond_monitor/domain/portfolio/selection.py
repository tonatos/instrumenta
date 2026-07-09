"""Unified bond eligibility, ranking, and profile-fallback selection."""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from bond_monitor.domain.bonds.models import RATING_ORDER, BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import Portfolio, RiskProfile
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    DEFAULT_DURATION_POLICY,
    BondSelectionContext,
    BondSelectionPolicy,
    DurationPolicy,
)
from bond_monitor.domain.screening.scorer import score_bonds_for_profile
from bond_monitor.domain.shared.formatting import format_date

_NORMAL_MIN_RATING_ORDINAL: int = RATING_ORDER["ruA-"]
_AGGRESSIVE_MIN_RATING_ORDINAL: int = RATING_ORDER["ruBB-"]


@dataclass(frozen=True)
class BondSelectionResult:
    """Ranked eligible bonds after profile-fallback chain."""

    bonds: list[BondRecord]
    fallback_note: str
    effective_profile_filter: RiskProfile | None


@dataclass(frozen=True)
class MaturityIndex:
    """Bonds sorted by effective end date (maturity or offer) for window queries."""

    _dates: tuple[date, ...]
    _bonds: tuple[BondRecord, ...]

    @classmethod
    def build(cls, universe: Sequence[BondRecord]) -> MaturityIndex:
        dated: list[tuple[date, BondRecord]] = []
        for bond in universe:
            end = bond.maturity_date or bond.offer_date
            if end is not None:
                dated.append((end, bond))
        dated.sort(key=lambda item: item[0])
        if not dated:
            return cls((), ())
        dates, bonds = zip(*dated, strict=True)
        return cls(dates, bonds)

    def bonds_between(self, min_date: date, max_date: date) -> list[BondRecord]:
        if not self._dates:
            return []
        left = bisect.bisect_left(self._dates, min_date)
        right = bisect.bisect_right(self._dates, max_date)
        return list(self._bonds[left:right])


@dataclass
class SelectionOptions:
    """Per-plan selection accelerators (maturity index + ranked-result cache)."""

    maturity_index: MaturityIndex | None = None
    ranked_cache: dict[tuple[object, ...], BondSelectionResult] = field(default_factory=dict)


def build_maturity_index(universe: Sequence[BondRecord]) -> MaturityIndex:
    return MaturityIndex.build(universe)


def has_usable_price(bond: BondRecord) -> bool:
    """Bond is purchasable when it has a positive dirty price."""
    return bond.price_per_lot_rub is not None and bond.price_per_lot_rub > 0


def api_tradable_filter(bonds: Sequence[BondRecord]) -> list[BondRecord]:
    """Keep only bonds tradable via T-Invest API."""
    return [b for b in bonds if b.api_trade_available_flag is True]


def risk_profile_filter(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
) -> list[BondRecord]:
    """Filter universe by risk profile (rating, subordination, risk level)."""
    result: list[BondRecord] = []
    for bond in bonds:
        if bond.has_default or bond.has_technical_default:
            continue

        rating_ordinal: int | None = (
            RATING_ORDER.get(bond.credit_rating) if bond.credit_rating else None
        )

        if profile == RiskProfile.NORMAL:
            if bond.subordinated_flag:
                continue
            if bond.risk_level == RiskLevel.HIGH:
                continue
            if rating_ordinal is None:
                continue
            if rating_ordinal < _NORMAL_MIN_RATING_ORDINAL:
                continue
        elif profile == RiskProfile.AGGRESSIVE:
            if rating_ordinal is not None and rating_ordinal < _AGGRESSIVE_MIN_RATING_ORDINAL:
                continue

        result.append(bond)
    return result


def portfolio_universe_filter(
    bonds: Sequence[BondRecord],
    portfolio: Portfolio,
) -> list[BondRecord]:
    """Universe filtered by portfolio strategy (profile + optional API-only)."""
    filtered = risk_profile_filter(bonds, portfolio.risk_profile)
    if portfolio.api_trade_only:
        filtered = api_tradable_filter(filtered)
    return filtered


from bond_monitor.domain.portfolio.put_offer import put_offer_buy_blocked


def _fallback_steps(profile: RiskProfile) -> tuple[RiskProfile | None, ...]:
    if profile == RiskProfile.AGGRESSIVE:
        return (RiskProfile.AGGRESSIVE, RiskProfile.NORMAL, None)
    return (RiskProfile.NORMAL, None)


def _profiles_tried_label(profile: RiskProfile) -> str:
    if profile == RiskProfile.NORMAL:
        return f"«{profile.value}» и любую без дефолта"
    return f"«{profile.value}», «{RiskProfile.NORMAL.value}» и любую без дефолта"


def _min_maturity_date(ctx: BondSelectionContext, policy: BondSelectionPolicy) -> date:
    return ctx.purchase_date + timedelta(days=policy.min_replacement_horizon_days)


def _maturity_window(ctx: BondSelectionContext, policy: BondSelectionPolicy) -> str:
    min_date = _min_maturity_date(ctx, policy)
    return f"[{format_date(min_date)}, {format_date(ctx.horizon_date)}]"


def bond_eligibility_reason(
    bond: BondRecord,
    ctx: BondSelectionContext,
    policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
    *,
    check_budget: bool = True,
) -> str | None:
    """Return rejection reason, or None if bond passes structural eligibility."""
    if policy.exclude_default and (bond.has_default or bond.has_technical_default):
        return "дефолт / тех.дефолт"

    if not has_usable_price(bond):
        return "нет рыночной цены"

    clean_pct = bond.last_price
    if clean_pct is not None and clean_pct < policy.min_clean_price_pct:
        return f"чистая цена {clean_pct:.1f}% < {policy.min_clean_price_pct:.0f}% номинала"

    blocked = put_offer_buy_blocked(bond, ctx.purchase_date)
    if blocked is not None:
        return blocked

    end = bond.maturity_date or bond.offer_date
    if end is None:
        return "нет даты погашения / оферты"

    min_maturity = _min_maturity_date(ctx, policy)
    if end < min_maturity:
        return f"погашение {format_date(end)} раньше окна (не ранее {format_date(min_maturity)})"
    if end > ctx.horizon_date:
        return f"погашение {format_date(end)} позже горизонта {format_date(ctx.horizon_date)}"

    if check_budget and ctx.budget_rub is not None:
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost > ctx.budget_rub:
            return f"лот {lot_cost:,.0f} ₽ > бюджета {ctx.budget_rub:,.0f} ₽"

    return None


def eligible_bonds(
    universe: Sequence[BondRecord],
    ctx: BondSelectionContext,
    policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
    *,
    profile_step: RiskProfile | None,
    check_budget: bool = True,
    selection_options: SelectionOptions | None = None,
) -> list[BondRecord]:
    """Structural + profile filter for one fallback step."""
    if selection_options is not None and selection_options.maturity_index is not None:
        search_pool: Sequence[BondRecord] = selection_options.maturity_index.bonds_between(
            _min_maturity_date(ctx, policy),
            ctx.horizon_date,
        )
    else:
        search_pool = universe

    if profile_step is not None:
        pool = risk_profile_filter(search_pool, profile_step)
    else:
        pool = [
            b
            for b in search_pool
            if not policy.exclude_default or (not b.has_default and not b.has_technical_default)
        ]

    if ctx.api_trade_only:
        pool = api_tradable_filter(pool)

    result: list[BondRecord] = []
    for bond in pool:
        if bond_eligibility_reason(bond, ctx, policy, check_budget=check_budget) is None:
            result.append(bond)
    return result


def rank_bonds(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
    *,
    key_rate: float,
    tax_rate: float,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> list[BondRecord]:
    """Rank bonds using portfolio profile scoring weights."""
    return score_bonds_for_profile(
        list(bonds),
        profile,
        key_rate=key_rate,
        tax_rate=tax_rate,
        duration_policy=duration_policy,
    )


def _fallback_note(
    ctx: BondSelectionContext,
    *,
    requested_step: RiskProfile | None,
    effective_step: RiskProfile | None,
) -> str:
    if effective_step == requested_step:
        return ""
    if effective_step == RiskProfile.NORMAL:
        return (
            f"профиль «{ctx.profile.value}» — нет кандидатов в окне "
            f"[{format_date(ctx.purchase_date)}, {format_date(ctx.horizon_date)}]; "
            f"выбрана бумага под NORMAL-профиль"
        )
    if effective_step is None:
        profiles_tried = (
            f"профиль «{ctx.profile.value}»"
            if ctx.profile == RiskProfile.NORMAL
            else f"профили «{ctx.profile.value}» и «{RiskProfile.NORMAL.value}»"
        )
        return (
            f"{profiles_tried} не дали кандидатов в окне; "
            "выбрана лучшая по скору бумага без профильных ограничений"
        )
    return ""


def explain_selection_failure(
    universe: Sequence[BondRecord],
    ctx: BondSelectionContext,
    policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
) -> str:
    """Human-readable reason when no bond could be selected."""
    profiles_tried = _profiles_tried_label(ctx.profile)

    if ctx.budget_rub is not None and ctx.budget_rub <= 0:
        return f"ожидаемый кэш {ctx.budget_rub:,.0f} ₽ ≤ 0"

    min_maturity_date = _min_maturity_date(ctx, policy)
    window = _maturity_window(ctx, policy)

    if min_maturity_date > ctx.horizon_date:
        return (
            f"окно реинвестиции слишком узкое — покупка с {format_date(ctx.purchase_date)}, "
            f"но мин. срок удержания {policy.min_replacement_horizon_days} дн. → "
            f"погашение замены не ранее {format_date(min_maturity_date)}, "
            f"а горизонт плана {format_date(ctx.horizon_date)}"
        )

    in_window: list[BondRecord] = []
    too_expensive: list[tuple[BondRecord, float]] = []
    budget = ctx.budget_rub

    for step in _fallback_steps(ctx.profile):
        for bond in eligible_bonds(universe, ctx, policy, profile_step=step, check_budget=False):
            if budget is not None:
                lot_cost = bond.price_per_lot_rub or 0.0
                if lot_cost > budget:
                    too_expensive.append((bond, lot_cost))
                    continue
            in_window.append(bond)

    if in_window:
        return (
            f"пробовали {profiles_tried}: в окне {window} есть "
            f"{len(in_window)} подходящих по сроку и бюджету бумаг(и), "
            f"но выбрать не удалось"
        )

    if too_expensive:
        min_lot = min(cost for _, cost in too_expensive)
        budget_label = f"{budget:,.0f}" if budget is not None else "—"
        return (
            f"пробовали {profiles_tried}: в окне {window} есть "
            f"{len(too_expensive)} бумаг(и), но мин. лот {min_lot:,.0f} ₽ "
            f"больше доступных {budget_label} ₽"
        )

    budget_suffix = (
        f"при доступных {ctx.budget_rub:,.0f} ₽"
        if ctx.budget_rub is not None
        else "по заданным критериям"
    )
    return (
        f"пробовали {profiles_tried}: в окне {window} "
        f"нет бумаг с погашением {budget_suffix} "
        f"(с учётом цены, лота и пут-оферт)"
    )


def _ranked_cache_key(
    ctx: BondSelectionContext,
    *,
    key_rate: float,
    tax_rate: float,
    duration_policy: DurationPolicy,
) -> tuple[object, ...]:
    budget = None if ctx.budget_rub is None else round(ctx.budget_rub)
    return (
        ctx.profile,
        ctx.horizon_date,
        ctx.purchase_date,
        budget,
        ctx.api_trade_only,
        key_rate,
        tax_rate,
        duration_policy,
    )


def select_ranked_bonds(
    universe: Sequence[BondRecord],
    ctx: BondSelectionContext,
    policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
    *,
    key_rate: float,
    tax_rate: float,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
    selection_options: SelectionOptions | None = None,
) -> BondSelectionResult:
    """Main entry: profile fallback chain, then rank by portfolio profile."""
    min_maturity_date = _min_maturity_date(ctx, policy)
    if min_maturity_date > ctx.horizon_date:
        return BondSelectionResult([], "", None)

    cache_key = _ranked_cache_key(
        ctx, key_rate=key_rate, tax_rate=tax_rate, duration_policy=duration_policy
    )
    if selection_options is not None:
        cached = selection_options.ranked_cache.get(cache_key)
        if cached is not None:
            return cached

    for step in _fallback_steps(ctx.profile):
        candidates = eligible_bonds(
            universe,
            ctx,
            policy,
            profile_step=step,
            selection_options=selection_options,
        )
        if not candidates:
            continue
        ranked = rank_bonds(
            candidates,
            ctx.profile,
            key_rate=key_rate,
            tax_rate=tax_rate,
            duration_policy=duration_policy,
        )
        if not ranked:
            continue
        note = _fallback_note(ctx, requested_step=ctx.profile, effective_step=step)
        result = BondSelectionResult(ranked, note, step)
        if selection_options is not None:
            selection_options.ranked_cache[cache_key] = result
        return result

    empty = BondSelectionResult([], "", None)
    if selection_options is not None:
        selection_options.ranked_cache[cache_key] = empty
    return empty


def select_best_bond(
    universe: Sequence[BondRecord],
    ctx: BondSelectionContext,
    policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
    *,
    key_rate: float,
    tax_rate: float,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
    selection_options: SelectionOptions | None = None,
) -> tuple[BondRecord | None, str]:
    """Pick top-ranked bond; second value is note or failure reason."""
    if ctx.budget_rub is not None and ctx.budget_rub <= 0:
        return None, explain_selection_failure(universe, ctx, policy)

    result = select_ranked_bonds(
        universe,
        ctx,
        policy,
        key_rate=key_rate,
        tax_rate=tax_rate,
        duration_policy=duration_policy,
        selection_options=selection_options,
    )
    if result.bonds:
        return result.bonds[0], result.fallback_note

    return None, explain_selection_failure(universe, ctx, policy)
