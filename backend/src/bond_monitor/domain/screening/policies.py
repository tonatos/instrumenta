"""Scoring policy for bond screening."""

from __future__ import annotations

from dataclasses import dataclass


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


DEFAULT_SCORING_POLICY = ScoringPolicy(key_rate=14.5, tax_rate=13.0)
