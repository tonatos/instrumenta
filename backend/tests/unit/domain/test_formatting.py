"""Unit tests for domain.shared.formatting."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.shared.formatting import MISSING_VALUE, format_date


def test_format_date_omits_year_for_reference_year() -> None:
    assert format_date(date(2026, 7, 28), reference=date(2026, 1, 1)) == "28 июля"


def test_format_date_includes_year_for_other_year() -> None:
    assert format_date(date(2027, 7, 28), reference=date(2026, 1, 1)) == "28 июля 2027"


def test_format_date_none_returns_missing_value() -> None:
    assert format_date(None) == MISSING_VALUE
