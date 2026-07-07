"""Smoke tests for portfolio CRUD endpoints: PATCH, positions, clear, slots.

Tests always clean up (delete) portfolios they create so they don't pollute
the shared dev database.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator

import pytest
from litestar.testing import TestClient

from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Test Portfolio") -> Generator[tuple[TestClient, str], None, None]:
    """Context-manager: spin up client, create portfolio, yield (client, id), delete on exit."""
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


def test_patch_portfolio_updates_name() -> None:
    with _portfolio_client("Original Name") as (client, pid):
        resp = client.patch(f"/api/v1/portfolios/{pid}", json={"name": "Updated Name"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Updated Name"


def test_patch_portfolio_updates_budget() -> None:
    with _portfolio_client() as (client, pid):
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
    with _portfolio_client() as (client, pid):
        # Auto-compose to populate positions
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")

        # Clear → 200 (explicit status_code=HTTP_200_OK set on handler)
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
    with _portfolio_client() as (client, pid):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/positions",
            json={"isin": "XX0000000000", "lots": 1},
        )
        # Bond not in universe → 404
        assert resp.status_code == 404, resp.text


def test_remove_position_not_found_isin_returns_404() -> None:
    with _portfolio_client() as (client, pid):
        resp = client.delete(f"/api/v1/portfolios/{pid}/positions/XX0000000000")
        assert resp.status_code == 404, resp.text
