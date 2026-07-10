"""Notification delivery policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AlertUrgency = Literal["normal", "soon", "critical"]


@dataclass(frozen=True)
class NotificationPolicy:
    put_offer_telegram_cooldown_hours: int = 24
    risk_telegram_min_urgency: AlertUrgency = "critical"
    include_put_offer_watch_in_alerts: bool = False


DEFAULT_NOTIFICATION_POLICY = NotificationPolicy()


def telegram_urgency_allowed(urgency: AlertUrgency) -> bool:
    return urgency == "critical"
