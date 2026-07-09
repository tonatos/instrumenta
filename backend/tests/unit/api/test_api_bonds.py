"""HTTP-level smoke tests for bonds API (DI wiring, not MOEX data)."""

from __future__ import annotations

from litestar.testing import TestClient

from bond_monitor.main import create_app


def test_list_bonds_accepts_filter_by_effective() -> None:
    """Regression: favorites_repo must be injected, not treated as a query param."""
    with TestClient(app=create_app()) as client:
        response = client.get("/api/v1/bonds/?filter_by=effective")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "bonds" in body
    assert "count" in body
    assert "source" in body


def test_list_bonds_accepts_rate_scenario_query() -> None:
    with TestClient(app=create_app()) as client:
        response = client.get("/api/v1/bonds/?filter_by=effective&rate_scenario=cut")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "bonds" in body


def test_get_bond_not_found_returns_404() -> None:
    with TestClient(app=create_app()) as client:
        response = client.get("/api/v1/bonds/___nonexistent___")

    assert response.status_code == 404
