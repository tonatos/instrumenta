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


def test_bond_to_response_includes_issuer_metadata() -> None:
    bond = BondRecord(
        secid="TEST",
        isin="RU000ATEST",
        name="Газпром001",
        issuer_name="ПАО Газпром",
        instrument_full_name="Газпром БО-001Р-02",
        sector="Энергетика",
        description="Корпоративная облигация",
    )
    response = bond_to_response(bond)
    assert response.issuer_name == "ПАО Газпром"
    assert response.instrument_full_name == "Газпром БО-001Р-02"
    assert response.sector == "Энергетика"
    assert response.description == "Корпоративная облигация"
