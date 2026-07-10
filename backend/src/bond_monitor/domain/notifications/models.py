"""Portfolio alert models for notifications and trading suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Literal

AlertUrgency = Literal["normal", "soon", "critical"]


class AlertKind(StrEnum):
    PUT_OFFER_ACTION = "put_offer_action"
    PUT_OFFER_WATCH = "put_offer_watch"
    RISK_ESCALATION = "risk_escalation"


@dataclass(frozen=True)
class Alert:
    """Detected portfolio event — source for suggestions and outbound notifications."""

    portfolio_id: str
    kind: AlertKind
    isin: str
    name: str
    lots: int
    figi: str | None
    reason: str
    urgency: AlertUrgency
    detail_key: str
    due_date: date | None = None
    chat_template: str | None = None
    suggested_price_pct: float | None = None
    market_price_pct: float | None = None
    risk_acknowledgeable: bool = False
    offer_window_status: str | None = None
    submission_start: date | None = None
    submission_end: date | None = None
    escalation_kinds: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "kind": self.kind.value,
            "isin": self.isin,
            "name": self.name,
            "lots": self.lots,
            "figi": self.figi,
            "reason": self.reason,
            "urgency": self.urgency,
            "detail_key": self.detail_key,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "chat_template": self.chat_template,
            "suggested_price_pct": self.suggested_price_pct,
            "market_price_pct": self.market_price_pct,
            "risk_acknowledgeable": self.risk_acknowledgeable,
            "offer_window_status": self.offer_window_status,
            "submission_start": (
                self.submission_start.isoformat() if self.submission_start else None
            ),
            "submission_end": self.submission_end.isoformat() if self.submission_end else None,
            "escalation_kinds": list(self.escalation_kinds),
        }
