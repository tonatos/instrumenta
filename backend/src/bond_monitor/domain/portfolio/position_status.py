"""Вычисление статуса позиции портфеля для UI и API."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from bond_monitor.domain.portfolio.models import PortfolioPosition

PositionStatus = Literal["pending", "active", "drift", "closed"]


def position_status(
    position: PortfolioPosition,
    *,
    is_trading: bool,
    today: date,
) -> PositionStatus:
    """Статус позиции; в TRADING плановые позиции — active (факт на счёте в advice)."""
    del today
    if not is_trading:
        return "active"
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
