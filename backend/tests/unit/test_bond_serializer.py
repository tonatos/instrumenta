"""Сериализация BondRecord → API DTO."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.interfaces.schemas.serializers import bond_to_response


def test_bond_to_response_includes_call_date() -> None:
    bond = BondRecord(
        secid="TEST",
        isin="RU000ATEST",
        name="Тест",
        call_date=date(2026, 8, 15),
    )
    response = bond_to_response(bond)
    assert response.call_date == date(2026, 8, 15)
