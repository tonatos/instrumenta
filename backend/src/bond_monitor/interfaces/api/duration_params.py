"""Parse duration-related API query parameters."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.portfolio.policies import RateScenario


def parse_rate_scenario(value: str | None) -> RateScenario:
    """Parse ``rate_scenario`` query param; invalid/missing → ``HOLD``."""
    if not value:
        return RateScenario.HOLD
    try:
        return RateScenario(value.lower())
    except ValueError:
        return RateScenario.HOLD


def parse_risk_profile(value: str | None) -> RiskProfile:
    """Parse ``risk_profile`` query param; invalid/missing → ``NORMAL``."""
    if not value:
        return RiskProfile.NORMAL
    try:
        return RiskProfile(value.lower())
    except ValueError:
        return RiskProfile.NORMAL
