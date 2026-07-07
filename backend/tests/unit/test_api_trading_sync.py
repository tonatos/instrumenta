"""Tests for POST /api/v1/portfolios/{id}/sync — trading sync hub."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Sync Test") -> Generator[tuple[TestClient, str], None, None]:
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
    return AccountSnapshot(
        account_id="acc-clean",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money_rub),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _attach_trading_portfolio(client: TestClient, pid: str) -> None:
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
        client.post(
            f"/api/v1/portfolios/{pid}/auto-compose",
        )
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mode"] == "trading"
        assert body["data"]["trading_started_at"] is not None


def test_sync_returns_trading_sync_response_shape() -> None:
    with _portfolio_client() as (client, pid):
        _attach_trading_portfolio(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_clean_snapshot(150_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
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
    with _portfolio_client() as (client, pid):
        resp = client.post(f"/api/v1/portfolios/{pid}/sync")
        assert resp.status_code == 400


def test_sync_returns_400_for_missing_broker_account() -> None:
    from bond_monitor.infrastructure.tinvest.trading_client import AccountNotFoundError

    with _portfolio_client() as (client, pid):
        _attach_trading_portfolio(client, pid)
        with patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            side_effect=AccountNotFoundError(
                "Счёт acc-clean не найден в T-Invest. "
                "Возможно, sandbox-счёт был пересоздан — перепривяжите портфель."
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 400, resp.text
        assert "не найден" in resp.json()["detail"]


def test_sync_passes_from_date_to_get_account_operations() -> None:
    with _portfolio_client() as (client, pid):
        _attach_trading_portfolio(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_clean_snapshot(150_000.0),
            ) as mock_snapshot,
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[],
            ) as mock_operations,
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 201, resp.text
        mock_snapshot.assert_called_once()
        mock_operations.assert_called_once()
        assert "from_date" in mock_operations.call_args.kwargs
