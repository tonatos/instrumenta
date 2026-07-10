"""Unit tests for notification fingerprinting and delivery cooldown."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from bond_monitor.domain.notifications.fingerprint import (
    alert_detail_key,
    alert_fingerprint,
    should_send_telegram,
)
from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.domain.notifications.policies import DEFAULT_NOTIFICATION_POLICY


def _alert(*, kind: AlertKind = AlertKind.PUT_OFFER_ACTION, isin: str = "RU000PO") -> Alert:
    return Alert(
        portfolio_id="portfolio-1",
        kind=kind,
        isin=isin,
        name="Test Bond",
        lots=2,
        figi="FIGI-1",
        reason="Test reason",
        urgency="soon",
        due_date=date(2026, 7, 31),
        detail_key="2026-07-31",
    )


def test_alert_fingerprint_is_stable() -> None:
    alert = _alert()
    fp1 = alert_fingerprint(alert)
    fp2 = alert_fingerprint(alert)
    assert fp1 == fp2
    assert len(fp1) == 32


def test_different_escalation_kinds_have_different_fingerprints() -> None:
    base = _alert(kind=AlertKind.RISK_ESCALATION, isin="RU000R1")
    alert_a = Alert(
        **{**base.__dict__, "detail_key": "default"},
    )
    alert_b = Alert(
        **{**base.__dict__, "detail_key": "ig_exit"},
    )
    assert alert_fingerprint(alert_a) != alert_fingerprint(alert_b)


def test_put_offer_detail_key_uses_submission_end() -> None:
    alert = Alert(
        portfolio_id="portfolio-1",
        kind=AlertKind.PUT_OFFER_ACTION,
        isin="RU000PO",
        name="Test Bond",
        lots=2,
        figi="FIGI-1",
        reason="Test reason",
        urgency="soon",
        due_date=date(2026, 8, 7),
        detail_key="2026-08-07",
    )
    assert alert_detail_key(alert) == "2026-08-07"


def test_should_send_telegram_respects_daily_cooldown() -> None:
    policy = DEFAULT_NOTIFICATION_POLICY
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    sent_at = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
    assert should_send_telegram(last_telegram_sent_at=sent_at, policy=policy, now=now) is False

    sent_yesterday = now - timedelta(hours=25)
    assert should_send_telegram(last_telegram_sent_at=sent_yesterday, policy=policy, now=now) is True
    assert should_send_telegram(last_telegram_sent_at=None, policy=policy, now=now) is True


def test_risk_critical_only_for_telegram_filter() -> None:
    from bond_monitor.domain.notifications.policies import telegram_urgency_allowed

    assert telegram_urgency_allowed("critical") is True
    assert telegram_urgency_allowed("soon") is False
    assert telegram_urgency_allowed("normal") is False
