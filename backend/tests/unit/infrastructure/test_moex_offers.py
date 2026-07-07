"""Unit tests for MOEX put/call offer enrichment."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.infrastructure.moex.offers_client import (
    PutOfferSchedule,
    _offer_schedule_from_rows,
    enrich_bonds_with_put_offers,
)


def _offers_block(rows: list[list[object]]) -> tuple[list[str], list[list[object]]]:
    columns = [
        "isin",
        "name",
        "issuevalue",
        "offerdate",
        "offerdatestart",
        "offerdateend",
        "facevalue",
        "faceunit",
        "price",
        "value",
        "agent",
        "offertype",
        "secid",
        "primary_boardid",
    ]
    return columns, rows


def test_offer_schedule_put_with_submission_window() -> None:
    """Investor put: nearest offer has a submission window."""
    columns, rows = _offers_block(
        [
            [
                "RU000A0JV4R9",
                "Bond",
                100_000_000,
                "2026-08-04",
                "2026-07-27",
                "2026-07-31",
                1000,
                "RUB",
                100,
                None,
                None,
                "Оферта",
                "RU000A0JV4R9",
                "TQCB",
            ]
        ]
    )
    schedule = _offer_schedule_from_rows(rows, columns, today=date(2026, 7, 7))
    assert schedule is not None
    assert schedule.is_issuer_call is False
    assert schedule.offer_date == date(2026, 8, 4)
    assert schedule.submission_start == date(2026, 7, 27)


def test_offer_schedule_regular_put_without_window_yet() -> None:
    """Regular put: no window on nearest offer, but history of windowed offers."""
    columns, rows = _offers_block(
        [
            [
                "RU000A0JUKX4",
                "Bond",
                100_000_000,
                "2025-03-04",
                "2025-02-21",
                "2025-02-28",
                1000,
                "RUB",
                100,
                None,
                None,
                "Оферта",
                "RU000A0JUKX4",
                "TQCB",
            ],
            [
                "RU000A0JUKX4",
                "Bond",
                100_000_000,
                "2027-09-03",
                None,
                None,
                1000,
                "RUB",
                100,
                None,
                None,
                "Оферта",
                "RU000A0JUKX4",
                "TQCB",
            ],
        ]
    )
    schedule = _offer_schedule_from_rows(rows, columns, today=date(2026, 7, 7))
    assert schedule is not None
    assert schedule.is_issuer_call is False
    assert schedule.offer_date == date(2027, 9, 3)


def test_offer_schedule_issuer_call_one_off_without_window_history() -> None:
    """Issuer call: single future offer without submission window or history."""
    columns, rows = _offers_block(
        [
            [
                "RU000A109PK2",
                "Сказка",
                300_000_000,
                "2026-10-06",
                None,
                None,
                1000,
                "RUB",
                100,
                None,
                None,
                "Оферта",
                "RU000A109PK2",
                "TQCB",
            ]
        ]
    )
    schedule = _offer_schedule_from_rows(rows, columns, today=date(2026, 7, 7))
    assert schedule is not None
    assert schedule.is_issuer_call is True
    assert schedule.offer_date == date(2026, 10, 6)


def test_enrich_issuer_call_sets_call_date_and_maturity_horizon() -> None:
    bond = BondRecord(
        secid="RU000A109PK2",
        isin="RU000A109PK2",
        name="Сказка",
        maturity_date=date(2027, 9, 30),
        offer_date=date(2026, 10, 6),
        effective_date=date(2026, 10, 6),
        days_to_maturity=91,
    )
    schedule = PutOfferSchedule(
        offer_date=date(2026, 10, 6),
        submission_start=None,
        submission_end=None,
        offer_price_pct=100.0,
        is_issuer_call=True,
    )

    def fake_load(_isins: set[str], _secid_by_isin: dict[str, str], _today: date) -> dict[str, PutOfferSchedule]:
        return {bond.isin: schedule}

    import bond_monitor.infrastructure.moex.offers_client as offers_client

    original = offers_client._load_schedules_for_isins
    offers_client._load_schedules_for_isins = fake_load
    try:
        enrich_bonds_with_put_offers([bond], today=date(2026, 7, 7))
    finally:
        offers_client._load_schedules_for_isins = original

    assert bond.call_date == date(2026, 10, 6)
    assert bond.offer_date is None
    assert bond.effective_date == date(2027, 9, 30)
    assert bond.days_to_maturity == (date(2027, 9, 30) - date(2026, 7, 7)).days


def test_enrich_put_keeps_offer_date() -> None:
    bond = BondRecord(
        secid="RU000A0JV4R9",
        isin="RU000A0JV4R9",
        name="Put bond",
        maturity_date=date(2034, 2, 1),
        offer_date=date(2026, 8, 4),
        effective_date=date(2026, 8, 4),
        days_to_maturity=28,
    )
    schedule = PutOfferSchedule(
        offer_date=date(2026, 8, 4),
        submission_start=date(2026, 7, 27),
        submission_end=date(2026, 7, 31),
        offer_price_pct=100.0,
        is_issuer_call=False,
    )

    import bond_monitor.infrastructure.moex.offers_client as offers_client

    original = offers_client._load_schedules_for_isins
    offers_client._load_schedules_for_isins = lambda *_a, **_k: {bond.isin: schedule}
    try:
        enrich_bonds_with_put_offers([bond], today=date(2026, 7, 7))
    finally:
        offers_client._load_schedules_for_isins = original

    assert bond.call_date is None
    assert bond.offer_date == date(2026, 8, 4)
    assert bond.effective_date == date(2026, 8, 4)
