"""Tests for POST /api/v1/accounts/sandbox — create funded sandbox account."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.domain.shared.money import Rub
from bond_monitor.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=create_app())


def test_create_sandbox_account_returns_funded_account(client: TestClient) -> None:
    with (
        patch(
            "bond_monitor.application.trading.broker.open_sandbox_account",
            return_value="acc-new-1",
        ) as open_mock,
        patch(
            "bond_monitor.application.trading.broker.sandbox_pay_in",
            return_value=Rub(150_000.0),
        ) as pay_in_mock,
    ):
        resp = client.post(
            "/api/v1/accounts/sandbox",
            json={"initial_amount_rub": 150_000.0, "name": "Test sandbox"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {
        "id": "acc-new-1",
        "name": "Test sandbox",
        "kind": "sandbox",
        "money_rub": 150_000.0,
        "linked_portfolio": None,
    }
    open_mock.assert_called_once()
    pay_in_mock.assert_called_once()
    assert pay_in_mock.call_args.args[1] == "acc-new-1"
    assert float(pay_in_mock.call_args.args[2]) == 150_000.0


def test_create_sandbox_account_rejects_non_positive_amount(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/accounts/sandbox",
        json={"initial_amount_rub": 0},
    )

    assert resp.status_code == 400, resp.text
