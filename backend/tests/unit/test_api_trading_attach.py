"""Tests for POST /api/v1/portfolios/{id}/attach — trading mode attach."""

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
def _portfolio_client(name: str = "Attach Test") -> Generator[tuple[TestClient, str], None, None]:
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


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=create_app())


def test_attach_returns_400_when_account_validation_fails(client: TestClient) -> None:
    with _portfolio_client() as (client, pid), patch(
        "bond_monitor.application.trading.trading_service.get_account_snapshot",
        return_value=_clean_snapshot(50_000.0),
    ):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )

    assert resp.status_code == 400, resp.text
    assert "не хватает" in resp.json()["detail"].lower()


def test_attach_rejects_account_already_linked_to_other_portfolio(client: TestClient) -> None:
    with (
        _portfolio_client("Уже в торговле") as (client, linked_pid),
        _portfolio_client("Новый портфель") as (_, new_pid),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=_clean_snapshot(150_000.0),
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        first_attach = client.post(
            f"/api/v1/portfolios/{linked_pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )
        assert first_attach.status_code == 201, first_attach.text

        second_attach = client.post(
            f"/api/v1/portfolios/{new_pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )

    assert second_attach.status_code == 400, second_attach.text
    assert "привязан" in second_attach.json()["detail"].lower()


def test_attach_returns_trading_portfolio_when_validation_passes(client: TestClient) -> None:
    with (
        _portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=_clean_snapshot(150_000.0),
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == PortfolioMode.TRADING.value
    assert body["account_id"] == "acc-clean"
    assert body["account_kind"] == "sandbox"
    assert body["initial_amount_rub"] == 150_000.0
