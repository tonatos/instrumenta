"""Composite scoring model for bond risk/reward ranking."""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from statistics import quantiles

from bond_monitor.domain.bonds.models import RATING_ORDER, BondRecord, CouponType, RiskLevel
from bond_monitor.domain.portfolio.models import RiskProfile

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
        return 0.0
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

    A bond yielding exactly the risk-free rate scores 0. The 95th percentile
    of the universe's spread anchors 100, and anything above it clips at 100.
    See ``_YTM_SCALE_PERCENTILE`` for the rationale.
    """
    if ytm_net is None:
        return 0.0
    spread = ytm_net - risk_free_net
    if spread <= 0:
        return 0.0
    if max_spread <= 0:
        return 50.0
    return min(100.0, spread / max_spread * 100.0)


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
    if bond.floating_coupon_flag or bond.coupon_type == CouponType.FLOATING:
        # Floating coupon: future size unknown, rate sensitivity risk
        penalties += 10.0
    if bond.coupon_type == CouponType.VARIABLE:
        # Variable coupon: next period unknown
        penalties += 8.0
    if bond.subordinated_flag:
        # In bankruptcy, subordinated holders get paid last
        penalties += 30.0
    if bond.call_date is not None:
        # Issuer can redeem early, cutting off expected coupons
        penalties += 5.0

    score = base - penalties + _rating_bonus(bond.credit_rating)
    return max(0.0, min(100.0, score))


def calc_liquidity_score(volume_rub: float | None, max_volume: float) -> float:
    """
    Logarithmic liquidity score [0, 100].

    Uses log scale because trading volumes span several orders of magnitude.
    """
    if not volume_rub or volume_rub <= 0 or max_volume <= 0:
        return 0.0
    return min(100.0, math.log10(volume_rub) / math.log10(max_volume) * 100.0)


def score_bonds(
    bonds: Sequence[BondRecord],
    key_rate: float = KEY_RATE_DEFAULT,
    tax_rate: float = TAX_RATE_DEFAULT,
) -> list[BondRecord]:
    """
    Compute composite scores for all bonds and return them sorted best-first.

    Side effect: populates ``bond.ytm_net = bond.ytm * (1 - tax_rate)`` for every
    bond before scoring. The screener and calculator rely on this being driven
    by the same ``tax_rate`` as the scoring itself.

    Score = YTM_score×0.40 + Risk_score×0.40 + Liquidity_score×0.20

    The YTM scale is anchored at the 95th percentile of ytm_net in the supplied
    universe (not the maximum), which keeps distressed/buggy outliers from
    collapsing the scale; bonds above the percentile clip at 100. Risk and
    liquidity scales are still relative, so scores depend on the full universe
    — always score the entire screened set at once.
    """
    if not bonds:
        return []

    after_tax_multiplier = 1.0 - tax_rate
    risk_free_net = key_rate * after_tax_multiplier

    for bond in bonds:
        bond.ytm_net = bond.ytm * after_tax_multiplier if bond.ytm is not None else None

    ytm_values: list[float] = [b.ytm_net for b in bonds if b.ytm_net is not None]
    scale_ytm_net = _ytm_scale_reference(ytm_values)
    if scale_ytm_net is None:
        scale_ytm_net = risk_free_net
    max_spread = max(scale_ytm_net - risk_free_net, 0.0)

    volumes = [b.filter_volume_rub for b in bonds if b.filter_volume_rub > 0]
    max_volume = max(volumes) if volumes else 1.0

    result: list[BondRecord] = []
    for bond in bonds:
        bond.ytm_score = calc_ytm_score(bond.ytm_net, risk_free_net, max_spread)
        bond.risk_score = calc_risk_score(bond)
        bond.liquidity_score = calc_liquidity_score(bond.filter_volume_rub, max_volume)
        bond.score = bond.ytm_score * 0.40 + bond.risk_score * 0.40 + bond.liquidity_score * 0.20
        result.append(bond)

    result.sort(key=lambda b: b.score or 0.0, reverse=True)
    logger.info(
        "Scored %d bonds (key_rate=%.2f%%, tax_rate=%.1f%%)",
        len(result),
        key_rate,
        tax_rate * 100,
    )
    return result


# Profile-specific weight presets for the portfolio module. The screener and
# the calculator stay on the default 40/40/20 mix; only ``score_bonds_for_profile``
# uses these. Keeping them here (rather than in ``core.portfolio_planner``)
# keeps every scoring weight in a single place.
# Веса (ytm, risk, liquidity) для скоринга под риск-профиль портфеля.
# Сумма должна быть 1.0; отклонение допустимо, но интерпретация скора
# (0..100) тогда теряет смысл.
#
# ``NORMAL`` — приоритет качеству эмитента (риск × 0.50); YTM весит меньше
# (× 0.30), потому что в этом профиле мы заведомо отсекаем низкие рейтинги.
#
# ``AGGRESSIVE`` — приоритет доходности (YTM × 0.65); риск-фильтр уже
# отсёк совсем junk-бумаги, дальше выбираем самые прибыльные. Раньше
# было (0.55, 0.25, 0.20), но по фидбэку — слишком осторожно: рейтинг
# уже учтён фильтром, дублировать его весом смысла нет, поэтому усилили
# YTM до 0.65.
_PROFILE_WEIGHTS: dict[RiskProfile, tuple[float, float, float]] = {
    RiskProfile.NORMAL: (0.30, 0.50, 0.20),
    RiskProfile.AGGRESSIVE: (0.65, 0.20, 0.15),
}


def score_bonds_for_profile(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
    *,
    key_rate: float = KEY_RATE_DEFAULT,
    tax_rate: float = TAX_RATE_DEFAULT,
) -> list[BondRecord]:
    """Аналог :func:`score_bonds`, но с весами под выбранный риск-профиль.

    * ``NORMAL`` — упор на качество (риск-скор × 0.50 при доходности × 0.30):
      выбираются более надёжные бумаги, даже если их YTM ниже.
    * ``AGGRESSIVE`` — упор на доходность (YTM × 0.55, риск × 0.25):
      допускает менее надёжные эмиссии ради бо́льшего ожидаемого дохода.

    Шкалы под YTM/ликвидность строятся по тому же принципу, что и в
    :func:`score_bonds` (95-й перцентиль для YTM, log-шкала для объёма),
    поэтому оба варианта совместимы по диапазону значений [0, 100].
    """
    if not bonds:
        return []

    after_tax_multiplier = 1.0 - tax_rate
    risk_free_net = key_rate * after_tax_multiplier
    weight_ytm, weight_risk, weight_liq = _PROFILE_WEIGHTS[profile]

    for bond in bonds:
        bond.ytm_net = bond.ytm * after_tax_multiplier if bond.ytm is not None else None

    ytm_values: list[float] = [b.ytm_net for b in bonds if b.ytm_net is not None]
    scale_ytm_net = _ytm_scale_reference(ytm_values)
    if scale_ytm_net is None:
        scale_ytm_net = risk_free_net
    max_spread = max(scale_ytm_net - risk_free_net, 0.0)

    volumes = [b.filter_volume_rub for b in bonds if b.filter_volume_rub > 0]
    max_volume = max(volumes) if volumes else 1.0

    result: list[BondRecord] = []
    for bond in bonds:
        bond.ytm_score = calc_ytm_score(bond.ytm_net, risk_free_net, max_spread)
        bond.risk_score = calc_risk_score(bond)
        bond.liquidity_score = calc_liquidity_score(bond.filter_volume_rub, max_volume)
        bond.score = (
            bond.ytm_score * weight_ytm
            + bond.risk_score * weight_risk
            + bond.liquidity_score * weight_liq
        )
        result.append(bond)

    result.sort(key=lambda b: b.score or 0.0, reverse=True)
    logger.info(
        "Profile-scored %d bonds (profile=%s, weights=%.2f/%.2f/%.2f)",
        len(result),
        profile.value,
        weight_ytm,
        weight_risk,
        weight_liq,
    )
    return result
