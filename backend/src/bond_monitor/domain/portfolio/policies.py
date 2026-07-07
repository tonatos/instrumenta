"""Domain policies — parameterized business rules (no magic globals)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bond_monitor.domain.portfolio.models import RiskProfile


@dataclass(frozen=True)
class PlanningPolicy:
    """Parameters for portfolio planning (cashflow, reinvest depth)."""

    reinvestment_gap_days: int = 2
    put_offer_reminder_days: int = 30
    max_reinvest_depth: int = 10
    coupon_cash_reinvest_interval_days: int = 30


DEFAULT_PLANNING_POLICY = PlanningPolicy()


@dataclass(frozen=True)
class PortfolioAllocationPolicy:
    """Diversification limits for auto-compose and top-up."""

    max_position_share: float = 0.30
    target_position_share: float = 0.18
    max_auto_positions: int = 10
    min_auto_positions: int = 4
    min_position_amount_rub: float = 5_000.0
    min_position_share: float = 0.03


DEFAULT_PORTFOLIO_ALLOCATION_POLICY = PortfolioAllocationPolicy()


@dataclass(frozen=True)
class BondSelectionPolicy:
    """Unified eligibility rules for compose / reinvest / top-up."""

    min_clean_price_pct: float = 85.0
    min_replacement_horizon_days: int = 10
    exclude_default: bool = True
    profile_fallback_steps: tuple[RiskProfile | None, ...] = (
        RiskProfile.AGGRESSIVE,
        RiskProfile.NORMAL,
        None,
    )


DEFAULT_BOND_SELECTION_POLICY = BondSelectionPolicy()


@dataclass(frozen=True)
class BondSelectionContext:
    """Runtime context for bond selection."""

    profile: RiskProfile
    horizon_date: date
    purchase_date: date
    budget_rub: float | None
    api_trade_only: bool


@dataclass(frozen=True)
class ScoringPolicy:
    """Parameters for bond scoring."""

    key_rate: float
    tax_rate: float
    ytm_weight: float = 0.40
    risk_weight: float = 0.40
    liquidity_weight: float = 0.20

    @property
    def weights(self) -> tuple[float, float, float]:
        return (self.ytm_weight, self.risk_weight, self.liquidity_weight)


@dataclass(frozen=True)
class ProfileScoringWeights:
    """Scoring weights per risk profile."""

    ytm: float
    risk: float
    liquidity: float


PROFILE_SCORING_WEIGHTS: dict[str, ProfileScoringWeights] = {
    "normal": ProfileScoringWeights(ytm=0.30, risk=0.50, liquidity=0.20),
    "aggressive": ProfileScoringWeights(ytm=0.65, risk=0.20, liquidity=0.15),
}
