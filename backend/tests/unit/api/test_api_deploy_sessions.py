"""API tests for deploy sessions."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from contextlib import contextmanager

from bond_monitor.application.bonds.bond_service import BondService
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_account_snapshot, make_bond


def _universe():
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
    return type("U", (), {"bonds": bonds})()


@contextmanager
def _trading_patches(money_rub: float = 500_000.0):
    with (
        patch.object(BondService, "load_universe", return_value=_universe()),
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(money_rub),
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
        yield


def test_create_deploy_session_returns_frozen_plan() -> None:
    with portfolio_client("Deploy Session") as (client, pid):
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-{pid[:8]}"
        )
        with _trading_patches(80_000.0):
            resp = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "active"
        assert body["progress"]["total"] >= 1
        assert len(body["items"]) >= 1


def test_create_deploy_session_conflict_when_active_exists() -> None:
    with portfolio_client("Deploy Conflict") as (client, pid):
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-{pid[:8]}"
        )
        with _trading_patches(80_000.0):
            first = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
            assert first.status_code == 201
            second = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
        assert second.status_code == 409


def test_create_deploy_session_after_completed_session() -> None:
    with portfolio_client("Deploy Recreate") as (client, pid):
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-{pid[:8]}"
        )
        with _trading_patches(80_000.0):
            created = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
            assert created.status_code == 201
            session_id = created.json()["id"]
            items = created.json()["items"]
            for item in items:
                client.post(
                    f"/api/v1/portfolios/{pid}/deploy-sessions/{session_id}/items/{item['id']}/skip"
                )
            second = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
        assert second.status_code == 201, second.text


def test_get_active_deploy_session() -> None:
    with portfolio_client("Deploy Active") as (client, pid):
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-{pid[:8]}"
        )
        with _trading_patches(80_000.0):
            created = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
            session_id = created.json()["id"]
            active = client.get(f"/api/v1/portfolios/{pid}/deploy-sessions/active")
        assert active.status_code == 200
        assert active.json()["id"] == session_id


def test_cancel_deploy_session() -> None:
    with portfolio_client("Deploy Cancel") as (client, pid):
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-{pid[:8]}"
        )
        with _trading_patches(80_000.0):
            created = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
            session_id = created.json()["id"]
            cancelled = client.delete(
                f"/api/v1/portfolios/{pid}/deploy-sessions/{session_id}"
            )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


def test_advice_includes_deploy_session_after_create() -> None:
    with portfolio_client("Deploy Advice") as (client, pid):
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-{pid[:8]}"
        )
        with _trading_patches(80_000.0):
            before = client.get(f"/api/v1/portfolios/{pid}/advice")
            assert before.status_code == 200, before.text
            client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
            advice = client.get(f"/api/v1/portfolios/{pid}/advice")
        assert advice.status_code == 200, advice.text
        assert advice.json()["deploy_session"] is not None
        assert advice.json()["deploy_session"]["status"] == "active"
