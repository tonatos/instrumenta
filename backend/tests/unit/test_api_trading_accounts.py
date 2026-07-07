"""Tests for GET /api/v1/accounts — broker account selector for trading attach."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import AccountKind, PortfolioMode
from bond_monitor.infrastructure.tinvest.trading_client import AccountInfo
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Linked Test") -> Generator[tuple[TestClient, str], None, None]:
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


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=create_app())


def test_list_accounts_returns_broker_accounts(client: TestClient) -> None:
    mock_accounts = [
        AccountInfo(
            id="acc-111",
            name="Sandbox 1",
            kind=AccountKind.SANDBOX,
            access_level="ACCOUNT_ACCESS_LEVEL_FULL_ACCESS",
            status="ACCOUNT_STATUS_OPEN",
            is_writable=True,
        ),
        AccountInfo(
            id="acc-222",
            name="Sandbox 2",
            kind=AccountKind.SANDBOX,
            access_level="ACCOUNT_ACCESS_LEVEL_READ_ONLY",
            status="ACCOUNT_STATUS_OPEN",
            is_writable=False,
        ),
    ]
    with patch(
        "bond_monitor.application.trading.trading_service.list_accounts",
        return_value=mock_accounts,
    ):
        resp = client.get("/api/v1/accounts?kind=sandbox")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == [
        {
            "id": "acc-111",
            "name": "Sandbox 1",
            "kind": "sandbox",
            "linked_portfolio": None,
        },
        {
            "id": "acc-222",
            "name": "Sandbox 2",
            "kind": "sandbox",
            "linked_portfolio": None,
        },
    ]


def test_list_accounts_shows_linked_portfolio(client: TestClient) -> None:
    from datetime import UTC, datetime

    from bond_monitor.domain.shared.money import Rub
    from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot

    clean_snapshot = AccountSnapshot(
        account_id="acc-linked",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(150_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    with (
        _portfolio_client("Уже в торговле") as (client, linked_pid),
        _portfolio_client("Новый портфель") as (_, _),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=clean_snapshot,
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        attach_resp = client.post(
            f"/api/v1/portfolios/{linked_pid}/attach",
            json={"account_id": "acc-linked", "kind": "sandbox"},
        )
        assert attach_resp.status_code == 201, attach_resp.text
        assert attach_resp.json()["mode"] == PortfolioMode.TRADING.value

        with patch(
            "bond_monitor.application.trading.trading_service.list_accounts",
            return_value=[
                AccountInfo(
                    id="acc-linked",
                    name="Sandbox linked",
                    kind=AccountKind.SANDBOX,
                    access_level="ACCOUNT_ACCESS_LEVEL_FULL_ACCESS",
                    status="ACCOUNT_STATUS_OPEN",
                    is_writable=True,
                ),
                AccountInfo(
                    id="acc-free",
                    name="Sandbox free",
                    kind=AccountKind.SANDBOX,
                    access_level="ACCOUNT_ACCESS_LEVEL_FULL_ACCESS",
                    status="ACCOUNT_STATUS_OPEN",
                    is_writable=True,
                ),
            ],
        ):
            resp = client.get("/api/v1/accounts?kind=sandbox")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    linked = next(item for item in data if item["id"] == "acc-linked")
    free = next(item for item in data if item["id"] == "acc-free")
    assert linked["linked_portfolio"] == {
        "id": linked_pid,
        "name": "Уже в торговле",
    }
    assert free["linked_portfolio"] is None
