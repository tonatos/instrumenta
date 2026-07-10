"""Unit tests for bond offer domain helpers."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.bonds.offers import (
    BondOfferView,
    OfferKind,
    OfferWindowStatus,
    bond_offer_view,
    offer_window_status,
    put_offer_awareness_message,
)
from bond_monitor.domain.portfolio.models import PortfolioPosition, PositionSourceType


def test_offer_window_status_unknown_when_no_submission_dates() -> None:
    """Samolet BO-P15: offer date known, window not published yet."""
    status = offer_window_status(
        offer_date=date(2026, 8, 7),
        submission_start=None,
        submission_end=None,
        as_of=date(2026, 7, 10),
    )
    assert status == OfferWindowStatus.UNKNOWN


def test_offer_window_status_open() -> None:
    status = offer_window_status(
        offer_date=date(2026, 8, 4),
        submission_start=date(2026, 7, 27),
        submission_end=date(2026, 7, 31),
        as_of=date(2026, 7, 28),
    )
    assert status == OfferWindowStatus.OPEN


def test_offer_window_status_not_open() -> None:
    status = offer_window_status(
        offer_date=date(2026, 8, 4),
        submission_start=date(2026, 7, 27),
        submission_end=date(2026, 7, 31),
        as_of=date(2026, 7, 20),
    )
    assert status == OfferWindowStatus.NOT_OPEN


def test_offer_window_status_closed() -> None:
    status = offer_window_status(
        offer_date=date(2026, 8, 4),
        submission_start=date(2026, 7, 27),
        submission_end=date(2026, 7, 31),
        as_of=date(2026, 8, 1),
    )
    assert status == OfferWindowStatus.CLOSED


def test_offer_window_status_expired() -> None:
    status = offer_window_status(
        offer_date=date(2026, 8, 4),
        submission_start=date(2026, 7, 27),
        submission_end=date(2026, 7, 31),
        as_of=date(2026, 8, 4),
    )
    assert status == OfferWindowStatus.EXPIRED


def test_bond_offer_view_samolet() -> None:
    bond = BondRecord(
        secid="RU000A109874",
        isin="RU000A109874",
        name="СамолетP15",
        offer_date=date(2026, 8, 7),
        offer_price_pct=100.0,
    )
    view = bond_offer_view(bond, date(2026, 7, 10))
    assert view is not None
    assert view.kind == OfferKind.PUT
    assert view.window_status == OfferWindowStatus.UNKNOWN
    assert "не объявлено" in put_offer_awareness_message(view)


def test_bond_offer_view_from_position() -> None:
    position = PortfolioPosition(
        isin="RU000A0JV4R9",
        secid="RU000A0JV4R9",
        name="Put bond",
        lots=1,
        lot_size=1,
        purchase_clean_price_pct=100.0,
        purchase_dirty_price_rub=1000.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=1000.0,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=date(2030, 1, 1),
        offer_date=date(2026, 8, 4),
        offer_submission_start=date(2026, 7, 27),
        offer_submission_end=date(2026, 7, 31),
        offer_price_pct=100.0,
        coupon_period_days=182,
        source=PositionSourceType.INITIAL,
    )
    view = bond_offer_view(position, date(2026, 7, 28))
    assert isinstance(view, BondOfferView)
    assert view.window_status == OfferWindowStatus.OPEN
