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
    """Статус позиции в TRADING; в SIMULATION всегда ``active``."""
    if not is_trading:
        return "active"
    if position.closed_at is not None:
        return "closed"
    actual = position.actual_lots
    if actual is None:
        return "active"
    if actual < position.lots:
        return "pending"
    if actual > position.lots:
        return "drift"
    if actual == position.lots and actual > 0:
        return "active"
    return "pending"


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
    """Позиции, не помеченные как закрытые."""
    return [p for p in positions if p.closed_at is None]


__all__ = [
    "PositionStatus",
    "open_positions",
    "position_status",
    "position_to_api_dict",
]
