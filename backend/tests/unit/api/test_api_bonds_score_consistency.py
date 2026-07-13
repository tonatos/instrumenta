"""API: list and detail bond scores must match for the same profile and scenario."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.application.bonds.bond_service import BondLoadResult, BondService
from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.main import create_app


def _bond() -> BondRecord:
    return BondRecord(
        secid="ZZYW2",
        isin="RU000A0ZZYW2",
        name="Test bond",
        ytm=24.0,
        risk_level=RiskLevel.MODERATE,
        credit_rating="ruA-",
        volume_rub=5_000_000,
        maturity_date=date(2028, 6, 1),
        duration_days=540.0,
        profile_scores={"conservative": 68.0, "normal": 74.0, "aggressive": 81.0},
        score=74.0,
        ytm_score=88.0,
        risk_score=62.0,
        liquidity_score=70.0,
    )


def test_list_and_detail_scores_match_with_rate_scenario() -> None:
    bond = _bond()

    def fake_load_screener(self, **kwargs):
        return BondLoadResult(bonds=[bond], source="test")

    def fake_load_by_secid(self, secid, **kwargs):
        return bond if secid == "ZZYW2" else None

    with patch.object(BondService, "load_screener_bonds", fake_load_screener):
        with patch.object(BondService, "load_by_secid", fake_load_by_secid):
            with TestClient(app=create_app()) as client:
                list_resp = client.get(
                    "/api/v1/bonds/?risk_profile=conservative&rate_scenario=cut",
                )
                detail_resp = client.get(
                    "/api/v1/bonds/ZZYW2?risk_profile=conservative&rate_scenario=cut",
                )

    assert list_resp.status_code == 200, list_resp.text
    assert detail_resp.status_code == 200, detail_resp.text
    list_score = list_resp.json()["bonds"][0]["score"]
    detail_score = detail_resp.json()["bond"]["score"]
    assert list_score == detail_score
    assert list_resp.json()["bonds"][0]["profile_scores"]["conservative"] == detail_score
