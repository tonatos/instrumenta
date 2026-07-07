"""Tests for DELETE /api/v1/accounts/sandbox/{account_id}."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import AccountKind, PortfolioMode
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Test portfolio") -> Generator[tuple[TestClient, str], None, None]:
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


def test_delete_sandbox_account_closes_unlinked_account(client: TestClient) -> None:
    with patch(
        "bond_monitor.application.trading.trading_service.close_sandbox_account",
    ) as close_mock:
        resp = client.delete("/api/v1/accounts/sandbox/acc-free-1")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "account_id": "acc-free-1",
        "deleted_portfolio_id": None,
    }
    close_mock.assert_called_once()


def test_delete_sandbox_account_removes_linked_portfolio(client: TestClient) -> None:
    clean_snapshot = AccountSnapshot(
        account_id="acc-linked-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(150_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    with (
        _portfolio_client("Уже в торговле") as (client, linked_pid),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=clean_snapshot,
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
        patch(
            "bond_monitor.application.trading.trading_service.close_sandbox_account",
        ) as close_mock,
    ):
        attach_resp = client.post(
            f"/api/v1/portfolios/{linked_pid}/attach",
            json={"account_id": "acc-linked-1", "kind": "sandbox"},
        )
        assert attach_resp.status_code == 201, attach_resp.text
        assert attach_resp.json()["mode"] == PortfolioMode.TRADING.value

        resp = client.delete("/api/v1/accounts/sandbox/acc-linked-1")

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "account_id": "acc-linked-1",
            "deleted_portfolio_id": linked_pid,
        }
        close_mock.assert_called_once()

        get_resp = client.get(f"/api/v1/portfolios/{linked_pid}")
        assert get_resp.status_code == 404, get_resp.text
