"""Tests for GET /api/v1/accounts — broker account selector for trading attach."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.infrastructure.tinvest.trading_client import AccountInfo
from conftest import linked_trading_account, portfolio_client


@pytest.fixture
def client() -> TestClient:
    from bond_monitor.main import create_app

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
        "bond_monitor.application.trading.broker.list_accounts",
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
    account_id = "acc-linked"
    with (
        linked_trading_account(account_id=account_id) as (client, linked_pid, _),
        portfolio_client("Новый портфель"),
        patch(
            "bond_monitor.application.trading.broker.list_accounts",
            return_value=[
                AccountInfo(
                    id=account_id,
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
        ),
    ):
        resp = client.get("/api/v1/accounts?kind=sandbox")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    linked = next(item for item in data if item["id"] == account_id)
    free = next(item for item in data if item["id"] == "acc-free")
    assert linked["linked_portfolio"] == {
        "id": linked_pid,
        "name": "Уже в торговле",
    }
    assert free["linked_portfolio"] is None
