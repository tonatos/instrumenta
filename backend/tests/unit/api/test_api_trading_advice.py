"""Tests for GET/POST /api/v1/portfolios/{id}/advice — stateless advisory hub."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.main import create_app
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_account_snapshot, make_bond


def test_advice_returns_trading_advice_response_shape() -> None:
    with portfolio_client("Advice Test") as (client, pid):
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
            patch(
                "bond_monitor.application.trading.broker.get_active_orders",
                return_value=[],
            ),
        ):
            resp = client.get(f"/api/v1/portfolios/{pid}/advice")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "holdings" in body
        assert "cashflow" in body
        assert "suggestions" in body
        assert "active_orders" in body
        assert "money_rub" in body
        assert "available_money_rub" in body
        assert "warnings" in body
        assert isinstance(body["holdings"], list)
        assert isinstance(body["suggestions"], list)


def test_advice_returns_404_for_missing_portfolio() -> None:
    with TestClient(app=create_app()) as client:
        resp = client.get("/api/v1/portfolios/nonexistent/advice")
        assert resp.status_code == 404


def test_advice_returns_400_for_simulation_portfolio() -> None:
    with portfolio_client("Advice Test") as (client, pid):
        resp = client.get(f"/api/v1/portfolios/{pid}/advice")
        assert resp.status_code == 400


def test_advice_suggests_buy_with_free_cash() -> None:
    from bond_monitor.application.bonds.bond_service import BondService
    from bond_monitor.domain.portfolio.plan_models import MIN_AUTO_POSITIONS

    bonds = [
        make_bond(
            isin=f"RU000A{i:03d}",
            figi=f"FIGI-{i}",
            price=100.0,
            ytm=18.0 + i,
            score=80.0 + i,
            maturity=date(2026, 12, 1),
        )
        for i in range(8)
    ]
    universe = type("U", (), {"bonds": bonds})()
    with portfolio_client("Advice Buy") as (client, pid):
        attach_trading_portfolio(client, pid, money_rub=80_000.0, auto_compose=False)
        with (
            patch.object(BondService, "load_universe", return_value=universe),
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(80_000.0),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.get_active_orders",
                return_value=[],
            ),
        ):
            resp = client.get(f"/api/v1/portfolios/{pid}/advice")

        assert resp.status_code == 200, resp.text
        suggestions = resp.json()["suggestions"]
        buy = [s for s in suggestions if s["kind"] == "buy"]
        assert len(buy) >= MIN_AUTO_POSITIONS, "expected diversified buy suggestions for free cash"


def test_advice_passes_from_date_to_operations() -> None:
    with portfolio_client("Advice Ops") as (client, pid):
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
            ),
        ):
            resp = client.get(f"/api/v1/portfolios/{pid}/advice")

        assert resp.status_code == 200, resp.text
        mock_snapshot.assert_called_once()
        mock_operations.assert_called_once()
        assert "from_date" in mock_operations.call_args.kwargs


def test_acknowledge_risk_alert_returns_204() -> None:
    from bond_monitor.application.bonds.bond_service import BondService

    bond = make_bond(isin="RU000A1", figi="FIGI-HOLD", name="Held Bond")
    universe = type("U", (), {"bonds": [bond]})()
    with portfolio_client("Risk Ack") as (client, pid):
        attach_trading_portfolio(client, pid, auto_compose=False)
        with patch.object(BondService, "load_universe", return_value=universe):
            resp = client.post(f"/api/v1/portfolios/{pid}/risk-alerts/RU000A1/acknowledge")
        assert resp.status_code == 204, resp.text
