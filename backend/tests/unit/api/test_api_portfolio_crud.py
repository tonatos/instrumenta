"""Smoke tests for portfolio CRUD endpoints: PATCH, positions, clear, slots.

Tests always clean up (delete) portfolios they create so they don't pollute
the shared dev database.
"""

from __future__ import annotations

import pytest
from litestar.testing import TestClient

from bond_monitor.main import create_app
from conftest import portfolio_client


def test_patch_portfolio_updates_name() -> None:
    with portfolio_client("Original Name") as (client, pid):
        resp = client.patch(f"/api/v1/portfolios/{pid}", json={"name": "Updated Name"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Updated Name"


def test_patch_portfolio_updates_budget() -> None:
    with portfolio_client() as (client, pid):
        resp = client.patch(
            f"/api/v1/portfolios/{pid}",
            json={"initial_amount_rub": 500_000.0},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["initial_amount_rub"] == 500_000.0


def test_patch_portfolio_not_found_returns_404() -> None:
    with TestClient(app=create_app()) as client:
        resp = client.patch("/api/v1/portfolios/nonexistent_id", json={"name": "X"})
        assert resp.status_code == 404, resp.text


def test_clear_portfolio_resets_positions_and_cash() -> None:
    with portfolio_client() as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")

        resp = client.post(f"/api/v1/portfolios/{pid}/clear")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["positions_count"] == 0
        assert pytest.approx(body["cash_balance_rub"], rel=1e-3) == 100_000.0


def test_clear_portfolio_not_found_returns_404() -> None:
    with TestClient(app=create_app()) as client:
        resp = client.post("/api/v1/portfolios/nonexistent_id/clear")
        assert resp.status_code == 404, resp.text


def test_add_position_not_found_bond_returns_404() -> None:
    with portfolio_client() as (client, pid):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/positions",
            json={"isin": "XX0000000000", "lots": 1},
        )
        assert resp.status_code == 404, resp.text


def test_remove_position_not_found_isin_returns_404() -> None:
    with portfolio_client() as (client, pid):
        resp = client.delete(f"/api/v1/portfolios/{pid}/positions/XX0000000000")
        assert resp.status_code == 404, resp.text
