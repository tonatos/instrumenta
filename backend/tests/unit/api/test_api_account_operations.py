"""Tests for GET /api/v1/portfolios/{id}/account-operations."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord
from conftest import attach_trading_portfolio, portfolio_client


def _sample_operations() -> list[OperationRecord]:
    return [
        OperationRecord(
            id="op-buy",
            type="OPERATION_TYPE_BUY",
            state="OPERATION_STATE_EXECUTED",
            date=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
            figi="FIGI123",
            instrument_uid="uid-1",
            instrument_type="bond",
            payment_rub=Rub(-10_050.0),
            quantity=10,
            price_pct=PriceUnitPct(1005.0),
            commission_rub=Rub(5.0),
        ),
        OperationRecord(
            id="op-coupon",
            type="OPERATION_TYPE_COUPON",
            state="OPERATION_STATE_EXECUTED",
            date=datetime(2026, 6, 15, 8, 0, tzinfo=UTC),
            figi="FIGI123",
            instrument_uid="uid-1",
            instrument_type="bond",
            payment_rub=Rub(420.0),
            quantity=0,
            price_pct=None,
            commission_rub=None,
        ),
        OperationRecord(
            id="op-input",
            type="OPERATION_TYPE_INPUT",
            state="OPERATION_STATE_EXECUTED",
            date=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
            figi="",
            instrument_uid="",
            instrument_type="currency",
            payment_rub=Rub(100_000.0),
            quantity=0,
            price_pct=None,
            commission_rub=None,
        ),
    ]


def test_account_operations_returns_sorted_history() -> None:
    bond = BondRecord(
        secid="TEST",
        isin="RU000ATEST",
        name="Тестовая облигация",
        figi="FIGI123",
        face_value=1000.0,
    )

    class _Universe:
        bonds = [bond]

    with portfolio_client("Ops History Test") as (client, pid):
        attach_trading_portfolio(client, pid, account_id="acc-ops")
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=_sample_operations(),
            ),
            patch.object(BondService, "load_universe", return_value=_Universe()),
        ):
            resp = client.get(f"/api/v1/portfolios/{pid}/account-operations")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "operations" in body
        ops = body["operations"]
        assert len(ops) == 3
        assert ops[0]["id"] == "op-coupon"
        assert ops[1]["id"] == "op-buy"
        assert ops[2]["id"] == "op-input"
        buy = next(op for op in ops if op["id"] == "op-buy")
        assert buy["type_label"] == "Покупка"
        assert buy["payment_rub"] == -10_050.0
        assert buy["price_pct"] == pytest.approx(100.5)
        assert buy["commission_rub"] == 5.0
        assert buy["quantity"] == 10


def test_account_operations_requires_trading_mode() -> None:
    with portfolio_client("Ops History Test") as (client, pid):
        resp = client.get(f"/api/v1/portfolios/{pid}/account-operations")
        assert resp.status_code == 400, resp.text
        assert "trading mode" in resp.json()["detail"].lower()
