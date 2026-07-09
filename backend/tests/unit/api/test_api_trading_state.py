"""Tests for GET /api/v1/portfolios/{id}/trading-state."""

from __future__ import annotations

from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.main import create_app
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_account_snapshot


def test_trading_state_returns_plan_and_advice() -> None:
    with portfolio_client("Trading State") as (client, pid):
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
            patch(
                "bond_monitor.application.trading.broker.get_active_orders",
                return_value=[],
            ) as mock_orders,
        ):
            resp = client.get(f"/api/v1/portfolios/{pid}/trading-state")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "plan" in body
        assert "advice" in body
        assert "slots" in body["plan"]
        assert "suggestions" in body["advice"]
        mock_snapshot.assert_called_once()
        mock_operations.assert_called_once()
        mock_orders.assert_called_once()


def test_trading_state_returns_404_for_missing_portfolio() -> None:
    with TestClient(app=create_app()) as client:
        resp = client.get("/api/v1/portfolios/nonexistent/trading-state")
        assert resp.status_code == 404
