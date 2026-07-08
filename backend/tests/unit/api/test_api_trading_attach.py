"""Tests for POST /api/v1/portfolios/{id}/attach — trading mode attach."""

from __future__ import annotations

from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import PortfolioMode
from conftest import portfolio_client
from factories import make_account_snapshot


def test_attach_allows_account_with_less_cash_than_initial(client: TestClient) -> None:
    """Soft attach: счёт с меньшим кэшем привязывается, effective_initial = max(план, счёт)."""
    with (
        portfolio_client("Attach Test", initial_amount_rub=100_000.0) as (test_client, pid),
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(50_000.0),
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        resp = test_client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["initial_amount_rub"] == 100_000.0


def test_attach_rejects_account_already_linked_to_other_portfolio(client: TestClient) -> None:
    with (
        portfolio_client("Уже в торговле") as (client_a, linked_pid),
        portfolio_client("Новый портфель") as (client_b, new_pid),
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(150_000.0),
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        first_attach = client_a.post(
            f"/api/v1/portfolios/{linked_pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )
        assert first_attach.status_code == 201, first_attach.text

        second_attach = client_b.post(
            f"/api/v1/portfolios/{new_pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )

    assert second_attach.status_code == 400, second_attach.text
    assert "привязан" in second_attach.json()["detail"].lower()


def test_attach_returns_trading_portfolio_when_validation_passes(client: TestClient) -> None:
    with (
        portfolio_client() as (test_client, pid),
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(150_000.0),
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        resp = test_client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == PortfolioMode.TRADING.value
    assert body["account_id"] == "acc-clean"
    assert body["account_kind"] == "sandbox"
    assert body["initial_amount_rub"] == 150_000.0
