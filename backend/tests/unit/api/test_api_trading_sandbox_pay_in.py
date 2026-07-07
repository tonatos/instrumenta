"""Tests for POST /api/v1/portfolios/{id}/sandbox-pay-in — sandbox top-up for testing."""

from __future__ import annotations

from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.shared.money import Rub
from bond_monitor.main import create_app
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_infra_account_snapshot


def _attach_production_portfolio(client: TestClient, pid: str) -> None:
    snapshot = make_infra_account_snapshot(
        150_000.0,
        account_id="acc-prod",
        account_kind=AccountKind.PRODUCTION,
    )
    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=snapshot,
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
        patch(
            "bond_monitor.application.trading.context.TradingContext.token",
            return_value="prod-token",
        ),
    ):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-prod", "kind": "production"},
        )
        assert resp.status_code == 201, resp.text


def test_sandbox_pay_in_adds_funds_to_attached_account() -> None:
    with portfolio_client("Pay-in Test") as (client, pid):
        attach_trading_portfolio(client, pid)
        with patch(
            "bond_monitor.application.trading.broker.sandbox_pay_in",
            return_value=Rub(170_000.0),
        ) as pay_in_mock:
            resp = client.post(
                f"/api/v1/portfolios/{pid}/sandbox-pay-in",
                json={"amount_rub": 20_000.0},
            )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["amount_added_rub"] == 20_000.0
        assert body["money_rub"] == 170_000.0
        pay_in_mock.assert_called_once()
        assert pay_in_mock.call_args.args[1] == "acc-clean"
        assert float(pay_in_mock.call_args.args[2]) == 20_000.0


def test_sandbox_pay_in_returns_400_for_simulation_portfolio() -> None:
    with portfolio_client("Pay-in Test") as (client, pid):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/sandbox-pay-in",
            json={"amount_rub": 10_000.0},
        )
        assert resp.status_code == 400


def test_sandbox_pay_in_returns_400_for_production_account() -> None:
    with portfolio_client("Pay-in Test") as (client, pid):
        _attach_production_portfolio(client, pid)
        resp = client.post(
            f"/api/v1/portfolios/{pid}/sandbox-pay-in",
            json={"amount_rub": 10_000.0},
        )
        assert resp.status_code == 400
        assert "песочниц" in resp.json()["detail"].lower()


def test_sandbox_pay_in_returns_404_for_missing_portfolio() -> None:
    with TestClient(app=create_app()) as client:
        resp = client.post(
            "/api/v1/portfolios/nonexistent/sandbox-pay-in",
            json={"amount_rub": 10_000.0},
        )
        assert resp.status_code == 404


def test_sandbox_pay_in_rejects_non_positive_amount() -> None:
    with portfolio_client("Pay-in Test") as (client, pid):
        attach_trading_portfolio(client, pid)
        resp = client.post(
            f"/api/v1/portfolios/{pid}/sandbox-pay-in",
            json={"amount_rub": 0},
        )
        assert resp.status_code == 400
