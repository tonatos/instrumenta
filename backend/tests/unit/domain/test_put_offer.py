"""Unit tests for put-offer business rules."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.offers import PutOfferDecision
from bond_monitor.domain.portfolio.models import PortfolioPosition, PositionSourceType
from bond_monitor.domain.portfolio.put_offer import (
    put_offer_awareness_due,
    put_offer_can_exercise,
    put_offer_submit_due,
)


def _samolet_position() -> PortfolioPosition:
    return PortfolioPosition(
        isin="RU000A109874",
        secid="RU000A109874",
        name="СамолетP15",
        lots=10,
        lot_size=1,
        purchase_clean_price_pct=99.0,
        purchase_dirty_price_rub=990.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=99_000.0,
        coupon_rate=12.0,
        face_value=1000.0,
        maturity_date=date(2027, 7, 30),
        offer_date=date(2026, 8, 7),
        offer_price_pct=100.0,
        coupon_period_days=91,
        source=PositionSourceType.ADOPTED,
    )


def test_samolet_no_submit_due_without_submission_window() -> None:
    today = date(2026, 7, 10)
    position = _samolet_position()
    assert put_offer_can_exercise(position, today) is False
    assert put_offer_submit_due(position, today) is False
    assert put_offer_awareness_due(position, today) is True


def test_submit_due_only_when_window_open_and_pending() -> None:
    today = date(2026, 7, 28)
    position = _samolet_position()
    position.offer_submission_start = date(2026, 7, 27)
    position.offer_submission_end = date(2026, 7, 31)
    assert put_offer_can_exercise(position, today) is True
    assert put_offer_submit_due(position, today) is True


def test_submit_due_false_when_hold_decision() -> None:
    today = date(2026, 7, 28)
    position = _samolet_position()
    position.offer_submission_start = date(2026, 7, 27)
    position.offer_submission_end = date(2026, 7, 31)
    position.put_offer_decision = PutOfferDecision.HOLD
    assert put_offer_submit_due(position, today) is False


def test_awareness_due_for_not_open_window() -> None:
    today = date(2026, 7, 20)
    position = _samolet_position()
    position.offer_submission_start = date(2026, 7, 27)
    position.offer_submission_end = date(2026, 7, 31)
    assert put_offer_can_exercise(position, today) is False
    assert put_offer_submit_due(position, today) is False
    assert put_offer_awareness_due(position, today) is True
