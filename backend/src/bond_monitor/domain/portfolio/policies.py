"""Domain policies — parameterized business rules (no magic globals)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from bond_monitor.domain.portfolio.models import RiskProfile


@dataclass(frozen=True)
class PlanningPolicy:
    """Parameters for portfolio planning (cashflow, reinvest depth)."""

    reinvestment_gap_days: int = 2
    put_offer_reminder_days: int = 30
    max_reinvest_depth: int = 10


DEFAULT_PLANNING_POLICY = PlanningPolicy()


@dataclass(frozen=True)
class PortfolioAllocationPolicy:
    """Diversification limits for auto-compose and cash deployment."""

    max_position_share: float = 0.30
    target_position_share: float = 0.18
    max_auto_positions: int = 10
    min_auto_positions: int = 4
    min_position_amount_rub: float = 5_000.0
    min_position_share: float = 0.03


DEFAULT_PORTFOLIO_ALLOCATION_POLICY = PortfolioAllocationPolicy()


@dataclass(frozen=True)
class BondSelectionPolicy:
    """Unified eligibility rules for compose / reinvest."""

    min_clean_price_pct: float = 85.0
    min_replacement_horizon_days: int = 10
    exclude_default: bool = True
    profile_fallback_steps: tuple[RiskProfile | None, ...] = (
        RiskProfile.AGGRESSIVE,
        RiskProfile.NORMAL,
        None,
    )


DEFAULT_BOND_SELECTION_POLICY = BondSelectionPolicy()


class RateScenario(StrEnum):
    """Сценарий по ключевой ставке — влияет на предпочтение по дюрации.

    * ``HOLD`` — ставка у пола / паузы: дюрация нейтральна (чистый carry).
    * ``CUT`` — цикл снижения продолжается: длинная дюрация даёт переоценку
      тела вверх, поэтому в ранжировании ей отдаётся приоритет.
    * ``HIKE`` — риск ужесточения: приоритет короткой дюрации.
    """

    HOLD = "hold"
    CUT = "cut"
    HIKE = "hike"


@dataclass(frozen=True)
class DurationPolicy:
    """Параметры учёта дюрации в отборе и ранжировании.

    Дефолт — «noop»: ``duration_score_weight == 0`` и
    ``max_weighted_duration_years is None`` не меняют текущее поведение
    стратегии (обратная совместимость с существующими тестами).
    """

    # Гардрейл риск-контура: верхний предел дюрации бумаги в корзине (годы).
    # Все включённые бумаги ≤ лимита → средневзвешенная корзины ≤ лимита.
    max_weighted_duration_years: float | None = None
    # Целевая дюрация под сценарий (годы). Зарезервировано для будущих
    # итераций (мягкое притяжение к таргету); сейчас не влияет на скор.
    target_duration_years: float | None = None
    # Вес duration-компоненты в composite score под ``rate_scenario``.
    # 0.0 = дюрация не влияет на ранжирование.
    duration_score_weight: float = 0.0
    rate_scenario: RateScenario = RateScenario.HOLD
    # Эффективная чувствительность флоатера к ключевой ставке (годы).
    floater_rate_duration_years: float = 0.0


DEFAULT_DURATION_POLICY = DurationPolicy()

_SCENARIO_DURATION_WEIGHT: dict[RateScenario, float] = {
    RateScenario.HOLD: 0.0,
    RateScenario.CUT: 0.20,
    RateScenario.HIKE: 0.20,
}

_SCENARIO_DEFAULT_TARGET_YEARS: dict[RateScenario, float | None] = {
    RateScenario.HOLD: None,
    RateScenario.CUT: 2.0,
    RateScenario.HIKE: 0.5,
}


def resolve_duration_policy(
    *,
    rate_scenario: RateScenario = RateScenario.HOLD,
    max_weighted_duration_years: float | None = None,
    target_duration_years: float | None = None,
) -> DurationPolicy:
    """Собрать ``DurationPolicy`` из глобального сценария и полей портфеля."""
    weight = _SCENARIO_DURATION_WEIGHT[rate_scenario]
    target = target_duration_years
    if target is None:
        target = _SCENARIO_DEFAULT_TARGET_YEARS[rate_scenario]
    if rate_scenario == RateScenario.HOLD:
        target = None
    return DurationPolicy(
        max_weighted_duration_years=max_weighted_duration_years,
        target_duration_years=target,
        duration_score_weight=weight,
        rate_scenario=rate_scenario,
    )


def duration_policy_for_portfolio(
    portfolio: object,
    *,
    rate_scenario: RateScenario = RateScenario.HOLD,
) -> DurationPolicy:
    """Собрать политику из query-сценария и сохранённых полей портфеля."""
    max_years = getattr(portfolio, "max_weighted_duration_years", None)
    target_years = getattr(portfolio, "target_duration_years", None)
    return resolve_duration_policy(
        rate_scenario=rate_scenario,
        max_weighted_duration_years=max_years,
        target_duration_years=target_years,
    )


@dataclass(frozen=True)
class RiskMonitorPolicy:
    """Thresholds for issuer risk escalation alerts on held positions."""

    # Ordinal floor for investment grade (BBB- = 3 in RATING_ORDER).
    investment_grade_ordinal_min: int = 3
    # Ratings at or below this ordinal are distress (CCC = -4).
    distress_rating_ordinal_max: int = -4
    # Minimum rating notch drop to trigger major_downgrade.
    major_downgrade_steps: int = 3


DEFAULT_RISK_MONITOR_POLICY = RiskMonitorPolicy()


@dataclass(frozen=True)
class BondSelectionContext:
    """Runtime context for bond selection."""

    profile: RiskProfile
    horizon_date: date
    purchase_date: date
    budget_rub: float | None
    api_trade_only: bool
