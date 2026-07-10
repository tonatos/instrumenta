"""Bond offer types and read-model helpers (put / call)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from bond_monitor.domain.shared.formatting import format_date


class OfferKind(StrEnum):
    PUT = "put"
    CALL = "call"


class OfferWindowStatus(StrEnum):
    """Lifecycle of an investor put-offer submission window."""

    UNKNOWN = "unknown"
    NOT_OPEN = "not_open"
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"


class PutOfferDecision(StrEnum):
    PENDING = "pending"
    EXERCISE = "exercise"
    HOLD = "hold"


PUT_OFFER_DECISION_LABELS: dict[PutOfferDecision, str] = {
    PutOfferDecision.PENDING: "Не решено",
    PutOfferDecision.EXERCISE: "Предъявить",
    PutOfferDecision.HOLD: "Держать до погашения",
}

OFFER_WINDOW_STATUS_LABELS: dict[OfferWindowStatus, str] = {
    OfferWindowStatus.UNKNOWN: "Окно подачи не объявлено",
    OfferWindowStatus.NOT_OPEN: "Приём заявок ещё не начался",
    OfferWindowStatus.OPEN: "Можно подать заявку",
    OfferWindowStatus.CLOSED: "Окно подачи закрыто",
    OfferWindowStatus.EXPIRED: "Оферта прошла",
}


class _OfferScheduleFields(Protocol):
    offer_date: date | None
    offer_submission_start: date | None
    offer_submission_end: date | None
    offer_price_pct: float | None
    call_date: date | None


@dataclass(frozen=True)
class BondOfferView:
    """Nearest investor put-offer snapshot for API/UI."""

    kind: OfferKind
    execution_date: date
    submission_start: date | None
    submission_end: date | None
    price_pct: float | None
    window_status: OfferWindowStatus
    moex_offer_type: str | None = None


def offer_window_status(
    *,
    offer_date: date | None,
    submission_start: date | None,
    submission_end: date | None,
    as_of: date,
) -> OfferWindowStatus | None:
    """Return window status for a put-offer, or ``None`` if there is no future offer."""
    if offer_date is None:
        return None
    if offer_date <= as_of:
        return OfferWindowStatus.EXPIRED
    if submission_start is None and submission_end is None:
        return OfferWindowStatus.UNKNOWN
    if submission_start is not None and as_of < submission_start:
        return OfferWindowStatus.NOT_OPEN
    if submission_end is not None and as_of > submission_end:
        return OfferWindowStatus.CLOSED
    return OfferWindowStatus.OPEN


def bond_offer_view(
    source: _OfferScheduleFields,
    as_of: date,
    *,
    kind: OfferKind = OfferKind.PUT,
    moex_offer_type: str | None = None,
) -> BondOfferView | None:
    """Build put-offer read-model from bond or position fields."""
    if source.offer_date is None:
        return None
    window_status = offer_window_status(
        offer_date=source.offer_date,
        submission_start=source.offer_submission_start,
        submission_end=source.offer_submission_end,
        as_of=as_of,
    )
    if window_status is None:
        return None
    return BondOfferView(
        kind=kind,
        execution_date=source.offer_date,
        submission_start=source.offer_submission_start,
        submission_end=source.offer_submission_end,
        price_pct=source.offer_price_pct,
        window_status=window_status,
        moex_offer_type=moex_offer_type,
    )


def put_offer_awareness_message(view: BondOfferView) -> str:
    """Human-readable informational text for watch reminders."""
    execution = format_date(view.execution_date)
    if view.window_status == OfferWindowStatus.UNKNOWN:
        return f"Пут-оферта {execution} — окно подачи ещё не объявлено эмитентом"
    if view.window_status == OfferWindowStatus.NOT_OPEN and view.submission_start is not None:
        return (
            f"Пут-оферта {execution} — приём заявок с "
            f"{format_date(view.submission_start)}"
        )
    if view.window_status == OfferWindowStatus.OPEN and view.submission_end is not None:
        return (
            f"Пут-оферта {execution} — подайте заявку до "
            f"{format_date(view.submission_end)} включительно"
        )
    return f"Пут-оферта {execution}"


def put_offer_action_message(view: BondOfferView) -> str:
    """Human-readable action text when submission window is open."""
    if view.submission_end is not None:
        return (
            f"Подайте заявку на пут-оферту до "
            f"{format_date(view.submission_end)} включительно "
            f"(исполнение {format_date(view.execution_date)})"
        )
    return f"Подайте заявку на пут-оферту (исполнение {format_date(view.execution_date)})"
