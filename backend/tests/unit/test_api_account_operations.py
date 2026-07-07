"""Tests for GET /api/v1/portfolios/{id}/account-operations."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot, OperationRecord
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Ops History Test") -> Generator[tuple[TestClient, str], None, None]:
    with TestClient(app=create_app()) as client:
        resp = client.post(
            "/api/v1/portfolios/",
            json={
                "name": name,
                "initial_amount_rub": 100_000.0,
                "horizon_date": "2027-01-01",
                "risk_profile": "normal",
            },
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        try:
            yield client, pid
        finally:
            client.delete(f"/api/v1/portfolios/{pid}")


def _clean_snapshot(money_rub: float = 150_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-ops",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money_rub),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _attach_trading_portfolio(client: TestClient, pid: str) -> None:
    with (
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=_clean_snapshot(150_000.0),
        ),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-ops", "kind": "sandbox"},
        )
        assert resp.status_code == 201, resp.text


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

    with _portfolio_client() as (client, pid):
        _attach_trading_portfolio(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
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
    with _portfolio_client() as (client, pid):
        resp = client.get(f"/api/v1/portfolios/{pid}/account-operations")
        assert resp.status_code == 400, resp.text
        assert "trading mode" in resp.json()["detail"].lower()
