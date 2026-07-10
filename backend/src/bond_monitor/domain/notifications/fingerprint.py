"""Deterministic fingerprints and delivery cooldown helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.domain.notifications.policies import DEFAULT_NOTIFICATION_POLICY, NotificationPolicy
from bond_monitor.domain.trading.ids import stable_id


def alert_detail_key(alert: Alert) -> str:
    return alert.detail_key


def alert_fingerprint(alert: Alert) -> str:
    return stable_id(alert.portfolio_id, alert.kind.value, f"{alert.isin}:{alert.detail_key}")


def should_send_telegram(
    *,
    last_telegram_sent_at: datetime | None,
    policy: NotificationPolicy = DEFAULT_NOTIFICATION_POLICY,
    now: datetime | None = None,
) -> bool:
    if last_telegram_sent_at is None:
        return True
    current = now or datetime.now(UTC)
    sent = last_telegram_sent_at
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    cooldown = timedelta(hours=policy.put_offer_telegram_cooldown_hours)
    return current - sent >= cooldown


def telegram_allowed_for_alert(
    alert: Alert,
    *,
    policy: NotificationPolicy = DEFAULT_NOTIFICATION_POLICY,
) -> bool:
    if alert.kind == AlertKind.PUT_OFFER_ACTION:
        return True
    if alert.kind == AlertKind.RISK_ESCALATION:
        min_urgency = policy.risk_telegram_min_urgency
        order = {"normal": 0, "soon": 1, "critical": 2}
        return order[alert.urgency] >= order[min_urgency]
    return False
