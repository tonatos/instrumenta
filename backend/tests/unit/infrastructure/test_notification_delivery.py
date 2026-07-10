"""Unit tests for notification delivery ledger and outbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.infrastructure.notifications.ledger_repository import LedgerRepository


def _alert() -> Alert:
    return Alert(
        portfolio_id="p1",
        kind=AlertKind.PUT_OFFER_ACTION,
        isin="RU000PO",
        name="Put Bond",
        lots=2,
        figi="FIGI-1",
        reason="Submit put-offer",
        urgency="soon",
        detail_key="2026-07-31",
    )


@pytest.fixture
def ledger(tmp_path: Path) -> LedgerRepository:
    return LedgerRepository(tmp_path / "ledger.db")


def test_ledger_insert_is_idempotent(ledger: LedgerRepository) -> None:
    alert = _alert()
    first = ledger.ensure_detected("fp-1", alert)
    second = ledger.ensure_detected("fp-1", alert)
    assert first is True
    assert second is False
    assert ledger.count() == 1


def test_ledger_mark_bus_and_telegram(ledger: LedgerRepository) -> None:
    alert = _alert()
    ledger.ensure_detected("fp-2", alert)
    now = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    assert ledger.mark_bus_published("fp-2", at=now) is True
    assert ledger.mark_bus_published("fp-2", at=now) is False
    assert ledger.mark_telegram_sent("fp-2", at=now) is True
    entry = ledger.get("fp-2")
    assert entry is not None
    assert entry.bus_published_at == now
    assert entry.telegram_sent_at == now


def test_ledger_pending_retries(ledger: LedgerRepository) -> None:
    alert = _alert()
    ledger.ensure_detected("fp-3", alert)
    pending = ledger.list_pending_bus()
    assert len(pending) == 1
    assert pending[0].fingerprint == "fp-3"
    assert json.loads(pending[0].payload_json)["isin"] == "RU000PO"
