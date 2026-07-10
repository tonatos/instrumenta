"""Вычисление статуса позиции портфеля для UI и API."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from bond_monitor.domain.bonds.offers import OfferKind, bond_offer_view
from bond_monitor.domain.portfolio.models import PortfolioPosition

PositionStatus = Literal["pending", "active", "drift", "closed"]


def position_status(
    position: PortfolioPosition,
    *,
    is_trading: bool,
    today: date,
) -> PositionStatus:
    """Статус позиции; в TRADING плановые позиции — active (факт на счёте в advice)."""
    del is_trading, today
    return "active"


def position_to_api_dict(
    position: PortfolioPosition,
    *,
    is_trading: bool,
    today: date,
) -> dict[str, Any]:
    """Сериализация позиции с вычисляемым ``status`` для API."""
    data = position.to_dict()
    data["status"] = position_status(position, is_trading=is_trading, today=today)
    view = bond_offer_view(position, today)
    data["offer_kind"] = OfferKind.PUT.value if view is not None else None
    data["offer_window_status"] = view.window_status.value if view is not None else None
    return data


def open_positions(positions: list[PortfolioPosition]) -> list[PortfolioPosition]:
    """Все позиции плана (факт на счёте — в advisory holdings)."""
    return list(positions)


__all__ = [
    "PositionStatus",
    "open_positions",
    "position_status",
    "position_to_api_dict",
]
