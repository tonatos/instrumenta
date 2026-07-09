"""Tests for GET /api/v1/bonds/by-isins and ISIN fallback on bond detail."""

from __future__ import annotations

from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.main import create_app


def test_bonds_by_isins_returns_enriched_bonds() -> None:
    bond = BondRecord(secid="TRDBB001", isin="RU000A105XJ1", name="ТРДБ Б0-01", score=72.0)

    with patch.object(BondService, "load_by_isins", return_value=[bond]):
        with TestClient(app=create_app()) as client:
            response = client.get("/api/v1/bonds/by-isins?isins=RU000A105XJ1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["bonds"][0]["isin"] == "RU000A105XJ1"
    assert body["bonds"][0]["secid"] == "TRDBB001"
    assert body["bonds"][0]["score"] == 72.0


def test_get_bond_falls_back_to_isin_lookup() -> None:
    bond = BondRecord(secid="TRDBB001", isin="RU000A105XJ1", name="ТРДБ Б0-01")

    with (
        patch.object(BondService, "load_by_secid", return_value=None),
        patch.object(BondService, "load_by_isins", return_value=[bond]) as load_by_isins,
    ):
        with TestClient(app=create_app()) as client:
            response = client.get("/api/v1/bonds/RU000A105XJ1")

    assert response.status_code == 200, response.text
    assert response.json()["bond"]["isin"] == "RU000A105XJ1"
    load_by_isins.assert_called_once_with(["RU000A105XJ1"])
