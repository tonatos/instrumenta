"""Portfolio notification domain."""

from bond_monitor.domain.notifications.fingerprint import (
    alert_detail_key,
    alert_fingerprint,
    should_send_telegram,
    telegram_allowed_for_alert,
)
from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.domain.notifications.policies import DEFAULT_NOTIFICATION_POLICY, NotificationPolicy
from bond_monitor.domain.notifications.rules import (
    AlertContext,
    collect_alerts,
    WORKER_ALERT_RULES,
)

__all__ = [
    "Alert",
    "AlertContext",
    "AlertKind",
    "DEFAULT_NOTIFICATION_POLICY",
    "NotificationPolicy",
    "WORKER_ALERT_RULES",
    "alert_detail_key",
    "alert_fingerprint",
    "collect_alerts",
    "should_send_telegram",
    "telegram_allowed_for_alert",
]
