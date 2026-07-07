"""Сериализация операций счёта → API DTO."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord
from bond_monitor.interfaces.schemas.serializers import account_operation_to_response


def _bond(figi: str = "FIGI123", *, face_value: float = 1000.0) -> BondRecord:
    return BondRecord(
        secid="GTLK1",
        isin="RU000AGTLK1",
        name="ГТЛК 2P-07",
        figi=figi,
        face_value=face_value,
    )


def test_account_operation_converts_bond_price_from_rub_to_pct() -> None:
    operation = OperationRecord(
        id="op-buy",
        type="OPERATION_TYPE_BUY",
        state="OPERATION_STATE_EXECUTED",
        date=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
        figi="FIGI123",
        instrument_uid="uid-1",
        instrument_type="bond",
        payment_rub=Rub(-10_045.0),
        quantity=10,
        price_pct=PriceUnitPct(1004.5),
        commission_rub=Rub(5.0),
    )
    response = account_operation_to_response(
        operation,
        bonds_by_figi={"FIGI123": _bond()},
    )
    assert response.price_pct == pytest.approx(100.45)


def test_account_operation_keeps_price_when_bond_unknown() -> None:
    operation = OperationRecord(
        id="op-buy",
        type="OPERATION_TYPE_BUY",
        state="OPERATION_STATE_EXECUTED",
        date=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
        figi="UNKNOWN",
        instrument_uid="uid-1",
        instrument_type="bond",
        payment_rub=Rub(-10_045.0),
        quantity=10,
        price_pct=PriceUnitPct(1004.5),
        commission_rub=None,
    )
    response = account_operation_to_response(operation, bonds_by_figi={})
    assert response.price_pct == 1004.5
