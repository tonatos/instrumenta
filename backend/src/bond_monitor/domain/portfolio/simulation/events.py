"""Scheduled simulation events for portfolio cashflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto

from bond_monitor.domain.portfolio.models import ReinvestmentTriggerReason


class SimEventKind(Enum):
    COUPON = auto()
    MATURITY = auto()
    PUT_OFFER = auto()
    DEPLOY_CASH = auto()


@dataclass(frozen=True)
class SimEvent:
    kind: SimEventKind
    date: date
    position_id: int | None = None
    source_position_isin: str | None = None
    trigger_reason: ReinvestmentTriggerReason | None = None
    confirmed_isin: str | None = None
    is_put: bool = False
    parent_generation: int = 0


@dataclass(order=True)
class ScheduledEvent:
    sort_key: tuple[date, int, int]
    event: SimEvent = field(compare=False)


def event_priority(kind: SimEventKind) -> int:
    """Same-day order: coupons → redemptions → deploy."""
    return {
        SimEventKind.COUPON: 0,
        SimEventKind.MATURITY: 1,
        SimEventKind.PUT_OFFER: 1,
        SimEventKind.DEPLOY_CASH: 2,
    }[kind]
