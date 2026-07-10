"""Deliver alerts to bus, ledger, and Telegram."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from bond_monitor.domain.notifications.fingerprint import (
    alert_fingerprint,
    should_send_telegram,
    telegram_allowed_for_alert,
)
from bond_monitor.domain.notifications.models import Alert
from bond_monitor.domain.notifications.policies import DEFAULT_NOTIFICATION_POLICY, NotificationPolicy
from bond_monitor.infrastructure.notifications.ledger_repository import LedgerRepository
from bond_monitor.infrastructure.notifications.notifications_repository import NotificationsRepository
from bond_monitor.infrastructure.notifications.redis_bus import NotificationBus
from bond_monitor.infrastructure.notifications.telegram_client import TelegramNotifier

logger = logging.getLogger(__name__)


def format_telegram_message(alert: Alert, portfolio_name: str) -> str:
    prefix = "🔴" if alert.urgency == "critical" else "🟡"
    return (
        f"{prefix} {portfolio_name}\n"
        f"{alert.name} ({alert.isin})\n"
        f"{alert.reason}"
    )


class DeliverNotificationsUseCase:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        bus: NotificationBus | None,
        telegram: TelegramNotifier,
        notifications_repo: NotificationsRepository | None = None,
        policy: NotificationPolicy | None = None,
    ) -> None:
        self._ledger = ledger
        self._bus = bus
        self._telegram = telegram
        self._notifications_repo = notifications_repo
        self._policy = policy

    @property
    def _effective_policy(self) -> NotificationPolicy:
        return self._policy or DEFAULT_NOTIFICATION_POLICY

    async def process_alert(self, alert: Alert, *, portfolio_name: str) -> None:
        fingerprint = alert_fingerprint(alert)
        self._ledger.ensure_detected(fingerprint, alert)
        await self._publish_bus(fingerprint, alert)
        await self._send_telegram_if_needed(fingerprint, alert, portfolio_name=portfolio_name)

    async def retry_pending(self, *, portfolio_names: dict[str, str]) -> None:
        for entry in self._ledger.list_pending_bus():
            payload = json.loads(entry.payload_json)
            alert = _alert_from_payload(payload)
            await self._publish_bus(entry.fingerprint, alert)
        for entry in self._ledger.list_pending_telegram():
            payload = json.loads(entry.payload_json)
            alert = _alert_from_payload(payload)
            portfolio_name = portfolio_names.get(alert.portfolio_id, alert.portfolio_id)
            await self._send_telegram_if_needed(entry.fingerprint, alert, portfolio_name=portfolio_name)

    async def _publish_bus(self, fingerprint: str, alert: Alert) -> None:
        entry = self._ledger.get(fingerprint)
        if entry is not None and entry.bus_published_at is not None:
            return
        now = datetime.now(UTC)
        published = False
        if self._bus is not None:
            try:
                self._bus.publish(
                    fingerprint=fingerprint,
                    portfolio_id=alert.portfolio_id,
                    kind=alert.kind.value,
                    payload=alert.to_payload(),
                    urgency=alert.urgency,
                )
                published = True
            except Exception:
                logger.exception("Redis publish failed for %s", fingerprint)
        if not published and self._notifications_repo is not None:
            await self._notifications_repo.upsert_from_bus(
                fingerprint=fingerprint,
                portfolio_id=alert.portfolio_id,
                kind=alert.kind.value,
                payload=alert.to_payload(),
                urgency=alert.urgency,
                created_at=now,
            )
            published = True
        if published:
            self._ledger.mark_bus_published(fingerprint, at=now)

    async def _send_telegram_if_needed(
        self,
        fingerprint: str,
        alert: Alert,
        *,
        portfolio_name: str,
    ) -> None:
        if not telegram_allowed_for_alert(alert, policy=self._effective_policy):
            return
        entry = self._ledger.get(fingerprint)
        if entry is not None and entry.telegram_sent_at is not None:
            if not should_send_telegram(
                last_telegram_sent_at=entry.telegram_sent_at,
                policy=self._effective_policy,
            ):
                return
        if not self._telegram.configured:
            return
        text = format_telegram_message(alert, portfolio_name)
        if self._telegram.send_message(text):
            self._ledger.mark_telegram_sent(fingerprint, at=datetime.now(UTC))


def _alert_from_payload(payload: dict) -> Alert:
    from bond_monitor.domain.notifications.models import AlertKind

    return Alert(
        portfolio_id=str(payload["portfolio_id"]),
        kind=AlertKind(str(payload["kind"])),
        isin=str(payload["isin"]),
        name=str(payload["name"]),
        lots=int(payload["lots"]),
        figi=payload.get("figi"),
        reason=str(payload["reason"]),
        urgency=payload["urgency"],
        detail_key=str(payload["detail_key"]),
        due_date=_parse_date(payload.get("due_date")),
        chat_template=payload.get("chat_template"),
        suggested_price_pct=payload.get("suggested_price_pct"),
        market_price_pct=payload.get("market_price_pct"),
        risk_acknowledgeable=bool(payload.get("risk_acknowledgeable", False)),
        offer_window_status=payload.get("offer_window_status"),
        submission_start=_parse_date(payload.get("submission_start")),
        submission_end=_parse_date(payload.get("submission_end")),
        escalation_kinds=tuple(payload.get("escalation_kinds") or ()),
    )


def _parse_date(value: str | None):
    from datetime import date

    if not value:
        return None
    return date.fromisoformat(value)
