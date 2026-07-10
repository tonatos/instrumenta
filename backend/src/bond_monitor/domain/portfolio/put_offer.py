"""Unified put-offer business rules."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.bonds.offers import (
    OfferWindowStatus,
    PutOfferDecision,
    bond_offer_view,
    offer_window_status,
)
from bond_monitor.domain.portfolio.models import PortfolioPosition
from bond_monitor.domain.portfolio.policies import DEFAULT_PLANNING_POLICY
from bond_monitor.domain.shared.formatting import format_date

PUT_OFFER_REMINDER_DAYS: int = DEFAULT_PLANNING_POLICY.put_offer_reminder_days


def _position_window_status(position: PortfolioPosition, as_of_date: date) -> OfferWindowStatus | None:
    return offer_window_status(
        offer_date=position.offer_date,
        submission_start=position.offer_submission_start,
        submission_end=position.offer_submission_end,
        as_of=as_of_date,
    )


def put_offer_buy_blocked(bond: BondRecord, as_of_date: date) -> str | None:
    """Return reason if put-offer window blocks purchase; else None."""
    status = offer_window_status(
        offer_date=bond.offer_date,
        submission_start=bond.offer_submission_start,
        submission_end=bond.offer_submission_end,
        as_of=as_of_date,
    )
    if status != OfferWindowStatus.CLOSED:
        return None
    assert bond.offer_submission_end is not None
    assert bond.offer_date is not None
    return (
        f"окно подачи по пут-оферте закрыто "
        f"{format_date(bond.offer_submission_end)}, оферта "
        f"{format_date(bond.offer_date)} — предъявить уже нельзя"
    )


def put_offer_submission_closed(position: PortfolioPosition, as_of_date: date) -> bool:
    """Окно подачи заявки по пут-оферте уже закрыто (или оферты нет)."""
    status = _position_window_status(position, as_of_date)
    return status in {OfferWindowStatus.CLOSED, OfferWindowStatus.EXPIRED, None}


def put_offer_can_exercise(position: PortfolioPosition, as_of_date: date) -> bool:
    """Можно ли **прямо сейчас** подать заявку на предъявление по пут-оферте."""
    return _position_window_status(position, as_of_date) == OfferWindowStatus.OPEN


def put_offer_awareness_due(position: PortfolioPosition, today: date) -> bool:
    """Информационное напоминание: оферта в горизонте, но действие ещё не требуется."""
    view = bond_offer_view(position, today)
    if view is None:
        return False
    if view.window_status not in {OfferWindowStatus.UNKNOWN, OfferWindowStatus.NOT_OPEN}:
        return False
    days_until = (view.execution_date - today).days
    return days_until <= PUT_OFFER_REMINDER_DAYS


def put_offer_submit_due(position: PortfolioPosition, today: date) -> bool:
    """Нужно ли генерировать action-напоминание по пут-оферте."""
    if position.put_offer_decision != PutOfferDecision.PENDING:
        return False
    if not put_offer_can_exercise(position, today):
        return False
    view = bond_offer_view(position, today)
    if view is None:
        return False
    if view.submission_end is not None:
        days_until_end = (view.submission_end - today).days
        return 0 <= days_until_end <= PUT_OFFER_REMINDER_DAYS
    days_until = (view.execution_date - today).days
    return days_until <= PUT_OFFER_REMINDER_DAYS


def position_plans_put_exit(
    position: PortfolioPosition,
    *,
    today: date,
    assume_best_put_outcome: bool,
) -> bool:
    """Whether portfolio plan should treat put-offer as planned exit."""
    if position.offer_date is None or position.offer_date <= today:
        return False
    if put_offer_submission_closed(position, today):
        return False
    offer_price = position.offer_price_pct if position.offer_price_pct is not None else 100.0
    if offer_price < 100.0:
        return False
    if position.put_offer_decision == PutOfferDecision.EXERCISE:
        return True
    if position.put_offer_decision == PutOfferDecision.HOLD:
        return False
    return assume_best_put_outcome
