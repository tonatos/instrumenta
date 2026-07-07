"""Tests for POST /api/v1/portfolios/{id}/sandbox-pay-in — sandbox top-up for testing."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Pay-in Test") -> Generator[tuple[TestClient, str], None, None]:
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
    from datetime import UTC, datetime

    return AccountSnapshot(
        account_id="acc-clean",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money_rub),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _attach_sandbox_portfolio(client: TestClient, pid: str) -> None:
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
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )
        assert resp.status_code == 201, resp.text


def test_sandbox_pay_in_adds_funds_to_attached_account() -> None:
    with _portfolio_client() as (client, pid):
        _attach_sandbox_portfolio(client, pid)
        with patch(
            "bond_monitor.application.trading.trading_service.sandbox_pay_in",
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
    with _portfolio_client() as (client, pid):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/sandbox-pay-in",
            json={"amount_rub": 10_000.0},
        )
        assert resp.status_code == 400


def _attach_production_portfolio(client: TestClient, pid: str) -> None:
    from datetime import UTC, datetime

    snapshot = AccountSnapshot(
        account_id="acc-prod",
        account_kind=AccountKind.PRODUCTION,
        money_rub=Rub(150_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    with (
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=snapshot,
        ),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
        patch(
            "bond_monitor.application.trading.trading_service.TradingService._token",
            return_value="prod-token",
        ),
    ):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-prod", "kind": "production"},
        )
        assert resp.status_code == 201, resp.text


def test_sandbox_pay_in_returns_400_for_production_account() -> None:
    with _portfolio_client() as (client, pid):
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
    with _portfolio_client() as (client, pid):
        _attach_sandbox_portfolio(client, pid)
        resp = client.post(
            f"/api/v1/portfolios/{pid}/sandbox-pay-in",
            json={"amount_rub": 0},
        )
        assert resp.status_code == 400
