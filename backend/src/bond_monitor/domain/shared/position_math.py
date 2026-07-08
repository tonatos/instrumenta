"""Shared position value calculations."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import PortfolioPosition


def position_cost_basis(position: PortfolioPosition) -> float:
    """Себестоимость позиции в ₽ по плановым лотам."""
    if position.purchase_amount_rub > 0:
        return position.purchase_amount_rub
    return position.purchase_dirty_price_rub * position.lots * position.lot_size
