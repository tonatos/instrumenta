"""Tests for T-Invest GetBonds disk cache."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import RiskLevel
from bond_monitor.infrastructure.tinvest import read_client


def test_get_tinvest_bonds_data_uses_disk_cache(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "tinvest_bonds.pkl"
    monkeypatch.setattr(read_client, "_BONDS_CACHE_FILE", cache_file)
    monkeypatch.setattr(read_client, "BONDS_CACHE_TTL_SECONDS", 3600)

    api_calls = {"count": 0}
    sample = {
        "RU000ATEST": read_client._TInvestBondData(
            figi="FIGI1",
            floating_coupon_flag=False,
            amortization_flag=False,
            perpetual_flag=False,
            subordinated_flag=False,
            for_qual_investor_flag=False,
            liquidity_flag=True,
            api_trade_available_flag=True,
            call_date=None,
            risk_level=RiskLevel.LOW,
        )
    }

    def fake_fetch(token: str):
        api_calls["count"] += 1
        return sample

    monkeypatch.setattr(read_client, "_fetch_all_bonds_from_api", fake_fetch)

    first = read_client.get_tinvest_bonds_data("token")
    second = read_client.get_tinvest_bonds_data("token")

    assert api_calls["count"] == 1
    assert first == second
    assert cache_file.exists()


def test_invalidate_tinvest_bonds_cache_forces_refetch(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "tinvest_bonds.pkl"
    monkeypatch.setattr(read_client, "_BONDS_CACHE_FILE", cache_file)
    monkeypatch.setattr(read_client, "BONDS_CACHE_TTL_SECONDS", 3600)

    api_calls = {"count": 0}

    def fake_fetch(token: str):
        api_calls["count"] += 1
        return {}

    monkeypatch.setattr(read_client, "_fetch_all_bonds_from_api", fake_fetch)

    read_client.get_tinvest_bonds_data("token")
    read_client.invalidate_tinvest_bonds_cache()
    read_client.get_tinvest_bonds_data("token")

    assert api_calls["count"] == 2
