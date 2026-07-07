"""Tests for POST /api/v1/portfolios/{id}/sync — trading sync hub."""

from __future__ import annotations

from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.main import create_app
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_account_snapshot


def test_sync_returns_trading_sync_response_shape() -> None:
    with portfolio_client("Sync Test") as (client, pid):
        attach_trading_portfolio(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(150_000.0),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "pending_operations" in body
        assert "drifts" in body
        assert "money_rub" in body
        assert "last_synced_at" in body
        assert isinstance(body["pending_operations"], list)
        if body["pending_operations"]:
            op = body["pending_operations"][0]
            assert "status" in op
            assert "urgency" in op


def test_sync_returns_404_for_missing_portfolio() -> None:
    with TestClient(app=create_app()) as client:
        resp = client.post("/api/v1/portfolios/nonexistent/sync")
        assert resp.status_code == 404


def test_sync_returns_400_for_simulation_portfolio() -> None:
    with portfolio_client("Sync Test") as (client, pid):
        resp = client.post(f"/api/v1/portfolios/{pid}/sync")
        assert resp.status_code == 400


def test_sync_returns_400_for_missing_broker_account() -> None:
    from bond_monitor.infrastructure.tinvest.trading_client import AccountNotFoundError

    with portfolio_client("Sync Test") as (client, pid):
        attach_trading_portfolio(client, pid)
        with patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            side_effect=AccountNotFoundError(
                "Счёт acc-clean не найден в T-Invest. "
                "Возможно, sandbox-счёт был пересоздан — перепривяжите портфель."
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 400, resp.text
        assert "не найден" in resp.json()["detail"]


def test_sync_passes_from_date_to_get_account_operations() -> None:
    with portfolio_client("Sync Test") as (client, pid):
        attach_trading_portfolio(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(150_000.0),
            ) as mock_snapshot,
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ) as mock_operations,
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 201, resp.text
        mock_snapshot.assert_called_once()
        mock_operations.assert_called_once()
        assert "from_date" in mock_operations.call_args.kwargs
