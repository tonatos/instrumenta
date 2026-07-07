"""Unified put-offer business rules."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import PortfolioPosition
from bond_monitor.domain.portfolio.policies import DEFAULT_PLANNING_POLICY
from bond_monitor.domain.shared.formatting import format_date

PUT_OFFER_REMINDER_DAYS: int = DEFAULT_PLANNING_POLICY.put_offer_reminder_days


def put_offer_buy_blocked(bond: BondRecord, as_of_date: date) -> str | None:
    """Return reason if put-offer window blocks purchase; else None."""
    if bond.offer_date is None or bond.offer_date <= as_of_date:
        return None
    if bond.offer_submission_end is None:
        return None
    if bond.offer_submission_end >= as_of_date:
        return None
    return (
        f"окно подачи по пут-оферте закрыто "
        f"{format_date(bond.offer_submission_end)}, оферта "
        f"{format_date(bond.offer_date)} — предъявить уже нельзя"
    )


def put_offer_submission_closed(position: PortfolioPosition, as_of_date: date) -> bool:
    """Окно подачи заявки по пут-оферте уже закрыто (или оферты нет)."""
    if position.offer_date is None or position.offer_date <= as_of_date:
        return True
    if position.offer_submission_end is None:
        return False
    return as_of_date > position.offer_submission_end


def put_offer_can_exercise(position: PortfolioPosition, as_of_date: date) -> bool:
    """Можно ли **прямо сейчас** подать заявку на предъявление по пут-оферте."""
    if put_offer_submission_closed(position, as_of_date):
        return False
    if position.offer_date is None or position.offer_date <= as_of_date:
        return False
    return not (
        position.offer_submission_start is not None and as_of_date < position.offer_submission_start
    )


def put_offer_submit_due(position: PortfolioPosition, today: date) -> bool:
    """Нужно ли генерировать pending put_offer_submit для позиции."""
    if position.offer_date is None or position.offer_date <= today:
        return False
    if put_offer_submission_closed(position, today):
        return False
    days_until = (position.offer_date - today).days
    if days_until > PUT_OFFER_REMINDER_DAYS:
        return False
    if position.offer_submission_start is not None and position.offer_submission_start > today:
        return False
    return True
