"""Domain policies — parameterized business rules (no magic globals)."""

from __future__ import annotations

from dataclasses import dataclass

from bond_monitor.domain.shared.money import Rub


@dataclass(frozen=True)
class PlanningPolicy:
    """Parameters for portfolio planning and auto-compose algorithms."""

    reinvestment_gap_days: int = 2
    put_offer_reminder_days: int = 30
    max_position_share: float = 0.30
    target_position_share: float = 0.18
    max_auto_positions: int = 10
    min_auto_positions: int = 4
    min_position_amount_rub: Rub = Rub(5_000.0)
    min_position_share: float = 0.03
    min_replacement_horizon_days: int = 30
    max_reinvest_depth: int = 10
    coupon_cash_reinvest_interval_days: int = 180


DEFAULT_PLANNING_POLICY = PlanningPolicy()


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
