"""Trading suggestion read-model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

SuggestionKind = Literal["buy", "reinvest", "reinvest_watch", "put_offer_reminder", "put_offer_watch", "sell"]


@dataclass(frozen=True)
class Suggestion:
    """Рекомендация к действию (не persisted pending)."""

    id: str
    kind: SuggestionKind
    isin: str
    name: str
    lots: int
    figi: str | None
    suggested_price_pct: float | None
    reason: str
    market_price_pct: float | None = None
    due_date: date | None = None
    source_isin: str | None = None
    chat_template: str | None = None
    urgency: Literal["normal", "soon", "critical"] = "normal"
    risk_acknowledgeable: bool = False
    offer_window_status: str | None = None
    submission_start: date | None = None
    submission_end: date | None = None
