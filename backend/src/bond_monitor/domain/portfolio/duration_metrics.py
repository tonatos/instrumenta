"""Weighted duration metrics for portfolio plan and trading advice."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import PortfolioPosition


class _DurationHolding(Protocol):
    isin: str
    market_value_rub: float | None


def weighted_duration_by_purchase(
    positions: Sequence[PortfolioPosition],
    universe_by_isin: dict[str, BondRecord],
) -> float | None:
    """Средневзвешенная дюрация (годы), взвешенная по ``purchase_amount_rub``."""
    weight_total = 0.0
    weighted_sum = 0.0
    for position in positions:
        bond = universe_by_isin.get(position.isin)
        if bond is None or bond.duration_years is None:
            continue
        weight = position.purchase_amount_rub
        weight_total += weight
        weighted_sum += weight * bond.duration_years
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total


def weighted_duration_by_market(
    holdings: Sequence[_DurationHolding],
    universe_by_isin: dict[str, BondRecord],
) -> float | None:
    """Средневзвешенная дюрация (годы), взвешенная по ``market_value_rub``."""
    weight_total = 0.0
    weighted_sum = 0.0
    for holding in holdings:
        bond = universe_by_isin.get(holding.isin)
        if bond is None or bond.duration_years is None:
            continue
        weight = holding.market_value_rub
        if weight is None or weight <= 0:
            continue
        weight_total += weight
        weighted_sum += weight * bond.duration_years
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total
