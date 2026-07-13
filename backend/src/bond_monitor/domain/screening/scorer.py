"""Composite scoring model for bond risk/reward ranking."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from statistics import quantiles

from bond_monitor.domain.bonds.models import RATING_ORDER, BondRecord, CouponType, RiskLevel
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_DURATION_POLICY,
    DurationPolicy,
    RateScenario,
)
from bond_monitor.domain.portfolio.duration_metrics import rate_sensitive_duration

logger = logging.getLogger(__name__)

# Defaults; overridden via env / app config (see app.py)
KEY_RATE_DEFAULT: float = 14.5  # % per annum
TAX_RATE_DEFAULT: float = 0.13  # personal income tax (НДФЛ) as a fraction, 0.13 = 13%

# Upper anchor of the YTM-score scale is the 95th percentile of ytm_net across
# the screened universe, not the absolute max. MOEX occasionally reports
# YIELD ≈ 80 000% for distressed/restructured issues (e.g. RU000A104UA4) which
# would otherwise collapse the linear scale and push every healthy bond's
# YTM-score to ~0. With a percentile anchor those outliers simply clip at 100.
_YTM_SCALE_PERCENTILE: float = 0.95

# Base risk score by T-Invest risk_level
_RISK_BASE: dict[RiskLevel, float] = {
    RiskLevel.LOW: 80.0,
    RiskLevel.MODERATE: 55.0,
    RiskLevel.HIGH: 25.0,
    RiskLevel.UNKNOWN: 45.0,
}

# Penalty when no credit rating is available (worse than known BB).
_UNRATED_PENALTY: float = -25.0

# Distress spread thresholds (net YTM above risk-free, percentage points).
# Sweet spot for aggressive VDO extends to ~28pp; YTM score caps above that.
# Decay to zero only beyond _DISTRESS_SPREAD_FULL_PP (~distressed junk).
_DISTRESS_SPREAD_START_PP: float = 28.0
_DISTRESS_YTM_DECAY_START_PP: float = 35.0
_DISTRESS_SPREAD_FULL_PP: float = 50.0
_DISTRESS_PENALTY_MAX: float = 40.0

# Investment-grade spreads get a higher distress threshold (BBB- and above).
_IG_DISTRESS_SPREAD_BONUS_PP: float = 12.0
_IG_MIN_RATING_ORDINAL: int = 3  # BBB-

# Aggressive profile: penalise low-spread «boring» bonds in composite score.
_AGGRESSIVE_BOREDOM_SPREAD_PP: float = 14.0
_AGGRESSIVE_BOREDOM_PENALTY_MAX: float = 22.0

# Aggressive profile: extra composite penalty for sub-IG yields implying distress.
_AGGRESSIVE_JUNK_SPREAD_PP: float = 28.0
_AGGRESSIVE_JUNK_PENALTY_MAX: float = 50.0

# Issuer call: coupon-reset trap — stronger than generic early redemption.
_CALL_TRAP_PENALTY: float = 12.0

# Absolute liquidity anchors (RUB/day); independent of universe max volume.
_LIQ_FLOOR_RUB: float = 500_000.0
_LIQ_GOOD_RUB: float = 10_000_000.0

# Rating bonus/penalty thresholds (ordinal ≥ threshold → bonus)
_RATING_BONUSES: list[tuple[int, float]] = [
    (12, 20.0),  # AAA
    (11, 16.0),  # AA+
    (10, 12.0),  # AA
    (9, 8.0),  # AA-
    (8, 4.0),  # A+
    (7, 0.0),  # A  (neutral)
    (6, -5.0),  # A-
    (5, -8.0),  # BBB+
    (4, -12.0),  # BBB
    (3, -16.0),  # BBB-
    (2, -20.0),  # BB+/BB
    (1, -22.0),  # BB-
    (0, -25.0),  # B+ and below
]


def _rating_bonus(rating: str | None) -> float:
    if rating is None:
        return _UNRATED_PENALTY
    ordinal = RATING_ORDER.get(rating)
    if ordinal is None:
        return 0.0
    for threshold, bonus in _RATING_BONUSES:
        if ordinal >= threshold:
            return bonus
    return -25.0


def calc_ytm_score(ytm_net: float | None, risk_free_net: float, max_spread: float) -> float:
    """
    Normalize excess yield above risk-free (after tax) to [0, 100].

    Linear up to ``_DISTRESS_SPREAD_START_PP``, flat cap until
    ``_DISTRESS_YTM_DECAY_START_PP``, then decay to 0 at
    ``_DISTRESS_SPREAD_FULL_PP``. High but still tradeable VDO yields
    (30–40% gross) keep their score; only extreme spreads decay.
    """
    if ytm_net is None:
        return 0.0
    spread = ytm_net - risk_free_net
    if spread <= 0:
        return 0.0
    if max_spread <= 0:
        return 50.0

    peak_spread = min(spread, _DISTRESS_SPREAD_START_PP)
    peak_score = min(100.0, peak_spread / max_spread * 100.0)
    if spread <= _DISTRESS_YTM_DECAY_START_PP:
        return peak_score

    if spread >= _DISTRESS_SPREAD_FULL_PP:
        return 0.0

    decay_frac = (spread - _DISTRESS_YTM_DECAY_START_PP) / (
        _DISTRESS_SPREAD_FULL_PP - _DISTRESS_YTM_DECAY_START_PP
    )
    return max(0.0, peak_score * (1.0 - decay_frac))


def _scoring_ytm_net(
    bond: BondRecord,
    risk_free_net: float,
    after_tax_multiplier: float,
) -> float | None:
    """
    YTM net for scoring only (display ``bond.ytm_net`` stays MOEX yield).

    Callable bonds: cap at coupon yield so phantom yield-to-call does not
    inflate scores. Missing coupon → neutral spread (risk-free only).
    """
    if bond.ytm_net is None:
        return None
    if bond.call_date is None:
        return bond.ytm_net
    if bond.coupon_rate is None:
        return risk_free_net
    coupon_net = bond.coupon_rate * after_tax_multiplier
    return min(bond.ytm_net, coupon_net)


def _ytm_scale_reference(ytm_values: Sequence[float]) -> float | None:
    """
    Return the YTM percentile used as the upper anchor of the score scale.

    Uses ``statistics.quantiles`` with the inclusive method so the cut points
    fall inside the observed data range (matches numpy's default percentile
    behaviour). Returns ``None`` for an empty sample.
    """
    if not ytm_values:
        return None
    if len(ytm_values) == 1:
        return ytm_values[0]
    cut_index = int(round(_YTM_SCALE_PERCENTILE * 100)) - 1
    cuts = quantiles(ytm_values, n=100, method="inclusive")
    return cuts[cut_index]


def calc_risk_score(bond: BondRecord) -> float:
    """
    Risk quality score [0, 100]: higher means safer.

    Starts from base score by risk_level, applies penalties for
    structural risks and bonuses/penalties for credit rating.
    """
    base = _RISK_BASE.get(bond.risk_level, _RISK_BASE[RiskLevel.UNKNOWN])

    penalties: float = 0.0
    if bond.amortization_flag:
        # Amortization complicates cash flow modelling
        penalties += 5.0
    if bond.coupon_type == CouponType.VARIABLE:
        # Variable coupon: next period unknown
        penalties += 8.0
    if bond.subordinated_flag:
        # In bankruptcy, subordinated holders get paid last
        penalties += 30.0
    if bond.call_date is not None:
        # Issuer call: post-call coupon unknown, no put protection
        penalties += _CALL_TRAP_PENALTY

    score = base - penalties + _rating_bonus(bond.credit_rating)
    return max(0.0, min(100.0, score))


def _distress_spread_start(bond: BondRecord) -> float:
    """Per-bond distress threshold; IG ratings tolerate wider spreads."""
    ordinal = RATING_ORDER.get(bond.credit_rating) if bond.credit_rating else None
    if ordinal is not None and ordinal >= _IG_MIN_RATING_ORDINAL:
        return _DISTRESS_SPREAD_START_PP + _IG_DISTRESS_SPREAD_BONUS_PP
    return _DISTRESS_SPREAD_START_PP


def calc_distress_penalty(bond: BondRecord, ytm_net: float | None, risk_free_net: float) -> float:
    """
    Penalty applied to risk_score when yield spread signals distress.

    Spread above the bond's distress start ramps linearly to
    ``_DISTRESS_PENALTY_MAX`` at ``_DISTRESS_SPREAD_FULL_PP``.
    BBB- and above get a higher start threshold.
    """
    spread = (ytm_net or 0.0) - risk_free_net
    start = _distress_spread_start(bond)
    if spread <= start:
        return 0.0
    span = _DISTRESS_SPREAD_FULL_PP - start
    if span <= 0:
        return _DISTRESS_PENALTY_MAX
    frac = (spread - start) / span
    return min(1.0, frac) * _DISTRESS_PENALTY_MAX


def calc_liquidity_score(volume_rub: float | None) -> float:
    """
    Logarithmic liquidity score [0, 100] on absolute volume anchors.

    ``_LIQ_FLOOR_RUB`` (min screener filter) maps to 0; ``_LIQ_GOOD_RUB``
    maps to 100. Independent of peer volumes in the scored universe.
    """
    if not volume_rub or volume_rub <= 0:
        return 0.0
    if volume_rub <= _LIQ_FLOOR_RUB:
        return 0.0
    if volume_rub >= _LIQ_GOOD_RUB:
        return 100.0
    log_span = math.log10(_LIQ_GOOD_RUB) - math.log10(_LIQ_FLOOR_RUB)
    if log_span <= 0:
        return 0.0
    frac = (math.log10(volume_rub) - math.log10(_LIQ_FLOOR_RUB)) / log_span
    return min(100.0, max(0.0, frac * 100.0))


def _final_risk_score(
    bond: BondRecord,
    risk_free_net: float,
    after_tax_multiplier: float,
) -> float:
    """Risk score after distress spread penalty."""
    scoring_ytm = _scoring_ytm_net(bond, risk_free_net, after_tax_multiplier)
    return max(
        0.0,
        calc_risk_score(bond) - calc_distress_penalty(bond, scoring_ytm, risk_free_net),
    )


def calc_aggressive_boredom_penalty(ytm_net: float | None, risk_free_net: float) -> float:
    """
    Composite-score penalty for low-yield bonds in the aggressive profile.

    AAA/AA issues at ~17–20% YTM should not outrank VDO at 30–40%.
    """
    spread = (ytm_net or 0.0) - risk_free_net
    if spread >= _AGGRESSIVE_BOREDOM_SPREAD_PP:
        return 0.0
    if _AGGRESSIVE_BOREDOM_SPREAD_PP <= 0:
        return 0.0
    frac = 1.0 - spread / _AGGRESSIVE_BOREDOM_SPREAD_PP
    return max(0.0, frac) * _AGGRESSIVE_BOREDOM_PENALTY_MAX


def calc_aggressive_junk_penalty(
    bond: BondRecord,
    ytm_net: float | None,
    risk_free_net: float,
) -> float:
    """
    Composite-score penalty for sub-IG bonds with extreme yield spreads.

    Distinguishes «good aggressive» VDO (BBB-/BB- at 30–40%) from
    distressed junk (BB and below at 55%+).
    """
    spread = (ytm_net or 0.0) - risk_free_net
    if spread <= _AGGRESSIVE_JUNK_SPREAD_PP:
        return 0.0
    ordinal = RATING_ORDER.get(bond.credit_rating) if bond.credit_rating else None
    if ordinal is not None and ordinal >= _IG_MIN_RATING_ORDINAL:
        return 0.0
    span = _DISTRESS_SPREAD_FULL_PP - _AGGRESSIVE_JUNK_SPREAD_PP
    if span <= 0:
        return _AGGRESSIVE_JUNK_PENALTY_MAX
    frac = min(1.0, (spread - _AGGRESSIVE_JUNK_SPREAD_PP) / span)
    return frac * _AGGRESSIVE_JUNK_PENALTY_MAX


# Profile-specific weight presets. Conservative and normal share weights;
# aggressive shifts toward YTM with boredom/junk penalties.
_PROFILE_WEIGHTS: dict[RiskProfile, tuple[float, float, float]] = {
    RiskProfile.CONSERVATIVE: (0.20, 0.60, 0.20),
    RiskProfile.NORMAL: (0.30, 0.50, 0.20),
    RiskProfile.AGGRESSIVE: (0.60, 0.25, 0.15),
}


def _composite_for_profile(
    bond: BondRecord,
    profile: RiskProfile,
    *,
    risk_free_net: float,
    after_tax_multiplier: float,
) -> float:
    """Weighted composite score for a single profile (components must be set)."""
    weight_ytm, weight_risk, weight_liq = _PROFILE_WEIGHTS[profile]
    score = (
        (bond.ytm_score or 0.0) * weight_ytm
        + (bond.risk_score or 0.0) * weight_risk
        + (bond.liquidity_score or 0.0) * weight_liq
    )
    if profile == RiskProfile.AGGRESSIVE:
        scoring_ytm = _scoring_ytm_net(bond, risk_free_net, after_tax_multiplier)
        boredom_ytm = scoring_ytm if scoring_ytm is not None else bond.ytm_net
        score = max(
            0.0,
            score
            - calc_aggressive_boredom_penalty(boredom_ytm, risk_free_net)
            - calc_aggressive_junk_penalty(bond, boredom_ytm, risk_free_net),
        )
    return score


def _prepare_bond_score_components(
    bonds: Sequence[BondRecord],
    *,
    key_rate: float,
    tax_rate: float,
) -> tuple[float, float, float]:
    """Populate ytm_net and component scores; return (risk_free_net, after_tax, max_spread)."""
    after_tax_multiplier = 1.0 - tax_rate
    risk_free_net = key_rate * after_tax_multiplier

    for bond in bonds:
        bond.ytm_net = bond.ytm * after_tax_multiplier if bond.ytm is not None else None

    ytm_values: list[float] = [
        net
        for b in bonds
        if (net := _scoring_ytm_net(b, risk_free_net, after_tax_multiplier)) is not None
    ]
    scale_ytm_net = _ytm_scale_reference(ytm_values)
    if scale_ytm_net is None:
        scale_ytm_net = risk_free_net
    max_spread = max(scale_ytm_net - risk_free_net, 0.0)

    for bond in bonds:
        scoring_ytm = _scoring_ytm_net(bond, risk_free_net, after_tax_multiplier)
        bond.ytm_score = calc_ytm_score(scoring_ytm, risk_free_net, max_spread)
        bond.risk_score = _final_risk_score(bond, risk_free_net, after_tax_multiplier)
        bond.liquidity_score = calc_liquidity_score(bond.filter_volume_rub)

    return risk_free_net, after_tax_multiplier, max_spread


def score_bonds_all_profiles(
    bonds: Sequence[BondRecord],
    key_rate: float = KEY_RATE_DEFAULT,
    tax_rate: float = TAX_RATE_DEFAULT,
) -> list[BondRecord]:
    """
    Compute profile-aware composite scores for all bonds and return sorted best-first.

    Side effect: populates ``ytm_net``, component scores and ``profile_scores`` for
    conservative / normal / aggressive. ``bond.score`` defaults to the normal profile.
    """
    if not bonds:
        return []

    mutable = list(bonds)
    risk_free_net, after_tax_multiplier, _ = _prepare_bond_score_components(
        mutable,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )

    result: list[BondRecord] = []
    for bond in mutable:
        bond.profile_scores = {
            profile.value: _composite_for_profile(
                bond,
                profile,
                risk_free_net=risk_free_net,
                after_tax_multiplier=after_tax_multiplier,
            )
            for profile in RiskProfile
        }
        bond.score = bond.profile_scores[RiskProfile.NORMAL.value]
        result.append(bond)

    result.sort(key=lambda b: b.score or 0.0, reverse=True)
    logger.info(
        "Scored %d bonds for all profiles (key_rate=%.2f%%, tax_rate=%.1f%%)",
        len(result),
        key_rate,
        tax_rate * 100,
    )
    return result


def calc_duration_adjustment(
    duration_years: float | None,
    *,
    scale_years: float,
    scenario: RateScenario,
    weight: float,
) -> float:
    """Прибавка к composite score за дюрацию под сценарий по ставке.

    * ``CUT`` — длинной дюрации выше бонус (переоценка тела при снижении).
    * ``HIKE`` — короткой дюрации выше бонус (защита при ужесточении).
    * ``HOLD`` / ``weight == 0`` / нет данных — нейтрально (0).

    Величина ограничена ``weight × 100`` и нормирована на разброс дюраций
    в универсе (``scale_years`` — максимум дюрации), поэтому влияет только
    на относительный порядок, а не на абсолютную шкалу 0..100.
    """
    if weight <= 0 or scenario == RateScenario.HOLD:
        return 0.0
    if duration_years is None or scale_years <= 0:
        return 0.0
    norm = min(1.0, max(0.0, duration_years / scale_years))
    factor = norm if scenario == RateScenario.CUT else 1.0 - norm
    return factor * weight * 100.0


def calc_target_duration_adjustment(
    duration_years: float | None,
    *,
    target_years: float | None,
    scale_years: float,
    weight: float,
) -> float:
    """Мягкий бонус за близость дюрации бумаги к целевой (soft-pull)."""
    if weight <= 0 or target_years is None:
        return 0.0
    if duration_years is None or scale_years <= 0:
        return 0.0
    distance = abs(duration_years - target_years) / scale_years
    closeness = max(0.0, 1.0 - distance)
    return closeness * weight * 50.0


def _duration_scale_years(
    bonds: Sequence[BondRecord],
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> float:
    duration_values = [
        d
        for b in bonds
        if (d := rate_sensitive_duration(b, duration_policy)) is not None
    ]
    return max(duration_values) if duration_values else 0.0


def _duration_adjustment_total(
    bond: BondRecord,
    *,
    duration_scale: float,
    duration_policy: DurationPolicy,
) -> float:
    weight = duration_policy.duration_score_weight
    sensitive_duration = rate_sensitive_duration(bond, duration_policy)
    return calc_duration_adjustment(
        sensitive_duration,
        scale_years=duration_scale,
        scenario=duration_policy.rate_scenario,
        weight=weight,
    ) + calc_target_duration_adjustment(
        sensitive_duration,
        target_years=duration_policy.target_duration_years,
        scale_years=duration_scale,
        weight=weight,
    )


def duration_adjustment_for_bond(
    bond: BondRecord,
    duration_policy: DurationPolicy,
    *,
    duration_scale: float,
) -> float:
    """Duration bonus/penalty for one bond (0 when policy is neutral)."""
    return _duration_adjustment_total(
        bond,
        duration_scale=duration_scale,
        duration_policy=duration_policy,
    )


def resolve_profile_scores(
    bond: BondRecord,
    duration_policy: DurationPolicy,
    *,
    duration_scale: float,
) -> dict[str, float]:
    """Apply duration adjustment to base profile scores without mutating the bond."""
    base = bond.profile_scores or {}
    if not base:
        return {}
    adjustment = duration_adjustment_for_bond(
        bond,
        duration_policy,
        duration_scale=duration_scale,
    )
    if adjustment == 0.0:
        return dict(base)
    return {
        key: min(100.0, max(0.0, value + adjustment))
        for key, value in base.items()
    }


def resolved_active_score(
    bond: BondRecord,
    profile: RiskProfile,
    duration_policy: DurationPolicy,
    *,
    duration_scale: float,
) -> float | None:
    scores = resolve_profile_scores(
        bond,
        duration_policy,
        duration_scale=duration_scale,
    )
    if scores:
        return scores.get(profile.value)
    return bond.score


def sort_bonds_by_resolved_score(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
    duration_policy: DurationPolicy,
) -> list[BondRecord]:
    """Sort bonds by profile-aware score including duration (no mutation)."""
    duration_scale = _duration_scale_years(bonds, duration_policy)
    return sorted(
        bonds,
        key=lambda b: resolved_active_score(
            b,
            profile,
            duration_policy,
            duration_scale=duration_scale,
        )
        or 0.0,
        reverse=True,
    )


def apply_duration_scoring(
    bonds: Sequence[BondRecord],
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
    *,
    active_profile: RiskProfile = RiskProfile.NORMAL,
) -> list[BondRecord]:
    """Return bonds with resolved profile scores and active score (no input mutation)."""
    from dataclasses import replace

    if (
        duration_policy.rate_scenario == RateScenario.HOLD
        and duration_policy.duration_score_weight <= 0
        and duration_policy.target_duration_years is None
    ):
        return list(bonds)

    duration_scale = _duration_scale_years(bonds, duration_policy)
    result: list[BondRecord] = []
    for bond in bonds:
        resolved = resolve_profile_scores(
            bond,
            duration_policy,
            duration_scale=duration_scale,
        )
        active = resolved.get(active_profile.value, bond.score)
        result.append(
            replace(
                bond,
                profile_scores=resolved,
                score=active,
            ),
        )
    result.sort(key=lambda b: b.score or 0.0, reverse=True)
    return result


def score_bonds_for_profile(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
    *,
    key_rate: float = KEY_RATE_DEFAULT,
    tax_rate: float = TAX_RATE_DEFAULT,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> list[BondRecord]:
    """Score bonds for a single profile on the supplied subset (selection pipeline)."""
    if not bonds:
        return []

    mutable = list(bonds)
    risk_free_net, after_tax_multiplier, _ = _prepare_bond_score_components(
        mutable,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )
    duration_scale = _duration_scale_years(mutable, duration_policy)

    result: list[BondRecord] = []
    for bond in mutable:
        base_score = _composite_for_profile(
            bond,
            profile,
            risk_free_net=risk_free_net,
            after_tax_multiplier=after_tax_multiplier,
        )
        bond.profile_scores = {profile.value: base_score}
        resolved = resolve_profile_scores(
            bond,
            duration_policy,
            duration_scale=duration_scale,
        )
        bond.score = resolved.get(profile.value, base_score)
        bond.profile_scores = resolved
        result.append(bond)

    result.sort(key=lambda b: b.score or 0.0, reverse=True)
    weight_ytm, weight_risk, weight_liq = _PROFILE_WEIGHTS[profile]
    logger.info(
        "Profile-scored %d bonds (profile=%s, weights=%.2f/%.2f/%.2f)",
        len(result),
        profile.value,
        weight_ytm,
        weight_risk,
        weight_liq,
    )
    return result
