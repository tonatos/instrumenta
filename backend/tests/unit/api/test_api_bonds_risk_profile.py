"""Tests for risk_profile query param on bonds list."""

from __future__ import annotations

from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.application.bonds.bond_service import BondLoadResult, BondService
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.main import create_app


def test_list_bonds_uses_aggressive_score_when_requested() -> None:
    bond = BondRecord(
        secid="TRDBB001",
        isin="RU000A105XJ1",
        name="ТРДБ Б0-01",
        score=55.0,
        profile_scores={"conservative": 60.0, "normal": 55.0, "aggressive": 72.0},
    )

    with patch.object(
        BondService,
        "load_screener_bonds",
        return_value=BondLoadResult(bonds=[bond], source="test"),
    ) as load_screener:
        with TestClient(app=create_app()) as client:
            response = client.get("/api/v1/bonds/?risk_profile=aggressive")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bonds"][0]["score"] == 72.0
    assert body["bonds"][0]["profile_scores"]["aggressive"] == 72.0
    load_screener.assert_called_once()
    assert load_screener.call_args.kwargs["risk_profile"] == RiskProfile.AGGRESSIVE
