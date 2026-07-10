"""Unit tests for notification delivery use case."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bond_monitor.application.notifications.deliver_use_case import DeliverNotificationsUseCase
from bond_monitor.domain.notifications.fingerprint import alert_fingerprint
from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.infrastructure.notifications.ledger_repository import LedgerRepository


def _risk_default_alert() -> Alert:
    return Alert(
        portfolio_id="p-def",
        kind=AlertKind.RISK_ESCALATION,
        isin="RU000DEF",
        name="Default Bond",
        lots=2,
        figi="FIGI-D",
        reason="Issuer default detected",
        urgency="critical",
        detail_key="default",
        risk_acknowledgeable=True,
    )


@pytest.mark.asyncio
async def test_deliver_risk_critical_telegram_with_default_policy(tmp_path) -> None:
    """Regression: explicit policy=None must not break Telegram gating."""
    ledger = LedgerRepository(tmp_path / "ledger.db")
    telegram = MagicMock()
    telegram.configured = True
    telegram.send_message.return_value = True
    deliver = DeliverNotificationsUseCase(
        ledger=ledger,
        bus=None,
        telegram=telegram,
        policy=None,
    )
    alert = _risk_default_alert()

    await deliver.process_alert(alert, portfolio_name="Test")

    telegram.send_message.assert_called_once()
    entry = ledger.get(alert_fingerprint(alert))
    assert entry is not None
    assert entry.telegram_sent_at is not None
