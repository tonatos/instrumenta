"""Tests for DELETE /api/v1/accounts/sandbox/{account_id}."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from conftest import linked_trading_account


@pytest.fixture
def client() -> TestClient:
    from bond_monitor.main import create_app

    return TestClient(app=create_app())


def test_delete_sandbox_account_closes_unlinked_account(client: TestClient) -> None:
    with patch(
        "bond_monitor.application.trading.broker.close_sandbox_account",
    ) as close_mock:
        resp = client.delete("/api/v1/accounts/sandbox/acc-free-1")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "account_id": "acc-free-1",
        "deleted_portfolio_id": None,
    }
    close_mock.assert_called_once()


def test_delete_sandbox_account_removes_linked_portfolio(client: TestClient) -> None:
    account_id = "acc-linked-1"
    with (
        linked_trading_account(account_id=account_id) as (client, linked_pid, _),
        patch(
            "bond_monitor.application.trading.broker.close_sandbox_account",
        ) as close_mock,
    ):
        resp = client.delete(f"/api/v1/accounts/sandbox/{account_id}")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "account_id": account_id,
            "deleted_portfolio_id": linked_pid,
        }
        close_mock.assert_called_once()

        get_resp = client.get(f"/api/v1/portfolios/{linked_pid}")
        assert get_resp.status_code == 404, get_resp.text
