"""T-Invest issuer/description metadata parsing and enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.infrastructure.tinvest.read_client import (
    AssetMetadata,
    _parse_asset_metadata,
    choose_issuer_name,
    enrich_bond_detail_metadata,
    enrich_bonds_from_tinvest,
)


def _asset(
    *,
    description: str = "",
    borrow_name: str = "",
    brand_company: str = "",
    brand_description: str = "",
    brand_name: str = "",
    brand_sector: str = "",
) -> SimpleNamespace:
    bond = SimpleNamespace(borrow_name=borrow_name) if borrow_name else None
    security = SimpleNamespace(bond=bond) if bond else None
    brand = SimpleNamespace(
        company=brand_company,
        description=brand_description,
        name=brand_name,
        sector=brand_sector,
    )
    return SimpleNamespace(
        description=description,
        security=security,
        brand=brand,
    )


def test_parse_asset_metadata_prefers_borrow_name() -> None:
    meta = _parse_asset_metadata(
        _asset(
            description="Описание выпуска",
            borrow_name="ПАО Газпром",
            brand_company="Газпром",
            brand_description="Бренд-описание",
            brand_sector="Энергетика",
        )
    )
    assert meta == AssetMetadata(
        issuer_name="ПАО Газпром",
        description="Описание выпуска",
        sector="Энергетика",
    )


def test_parse_asset_metadata_falls_back_to_brand() -> None:
    meta = _parse_asset_metadata(
        _asset(
            brand_company="ПАО МТС",
            brand_description="Телеком-оператор",
            brand_name="МТС",
            brand_sector="Телекоммуникации",
        )
    )
    assert meta.issuer_name == "ПАО МТС"
    assert meta.description == "Телеком-оператор"
    assert meta.sector == "Телекоммуникации"


def test_choose_issuer_name_chain() -> None:
    assert (
        choose_issuer_name(
            borrow_name="",
            brand_company="",
            brand_name="",
            instrument_full_name="Газпром БО-001Р-02",
            fallback_name="Газпром001",
        )
        == "Газпром БО-001Р-02"
    )


def test_enrich_bonds_from_tinvest_sets_instrument_full_name_and_sector(monkeypatch) -> None:
    from bond_monitor.infrastructure.tinvest import read_client as module

    monkeypatch.setattr(
        module,
        "get_tinvest_bonds_data",
        lambda _token: {
            "RU000ATEST": module._TInvestBondData(
                figi="FIGI1",
                floating_coupon_flag=False,
                amortization_flag=False,
                perpetual_flag=False,
                subordinated_flag=False,
                for_qual_investor_flag=False,
                liquidity_flag=True,
                api_trade_available_flag=True,
                call_date=None,
                risk_level=RiskLevel.MODERATE,
                instrument_full_name="Газпром БО-001Р-02",
                sector="Энергетика",
                asset_uid="asset-uid-1",
            )
        },
    )

    bond = BondRecord(secid="TEST", isin="RU000ATEST", name="Газпром001")
    enrich_bonds_from_tinvest([bond], "token")

    assert bond.instrument_full_name == "Газпром БО-001Р-02"
    assert bond.sector == "Энергетика"
    assert bond.asset_uid == "asset-uid-1"
    assert bond.tinvest_enriched is True


def test_enrich_bond_detail_metadata_applies_asset_fields(monkeypatch, tmp_path) -> None:
    from bond_monitor.infrastructure.tinvest import read_client as module

    monkeypatch.setattr(module, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(module, "_METADATA_CACHE_FILE", tmp_path / "tinvest_asset_metadata.json")

    bond = BondRecord(
        secid="TEST",
        isin="RU000ATEST",
        name="Газпром001",
        instrument_full_name="Газпром БО-001Р-02",
        asset_uid="asset-uid-1",
        tinvest_enriched=True,
    )

    monkeypatch.setattr(
        module,
        "_fetch_asset_metadata_from_api",
        lambda token, asset_uid: AssetMetadata(
            issuer_name="ПАО Газпром",
            description="Корпоративная облигация",
            sector="Энергетика",
        ),
    )

    enrich_bond_detail_metadata(bond, "token")

    assert bond.issuer_name == "ПАО Газпром"
    assert bond.description == "Корпоративная облигация"
    assert bond.sector == "Энергетика"


def test_enrich_bond_detail_metadata_skips_without_token() -> None:
    bond = BondRecord(
        secid="TEST",
        isin="RU000ATEST",
        name="Газпром001",
        asset_uid="asset-uid-1",
    )
    enrich_bond_detail_metadata(bond, "")
    assert bond.issuer_name == ""
    assert bond.description == ""


def test_enrich_bond_detail_metadata_uses_metadata_cache(monkeypatch, tmp_path) -> None:
    from bond_monitor.infrastructure.tinvest import read_client as module

    cache_file = tmp_path / "tinvest_asset_metadata.json"
    monkeypatch.setattr(module, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(module, "_METADATA_CACHE_FILE", cache_file)

    bond = BondRecord(
        secid="TEST",
        isin="RU000ATEST",
        name="Газпром001",
        asset_uid="asset-uid-1",
    )

    api = MagicMock(
        return_value=AssetMetadata(
            issuer_name="ПАО Газпром",
            description="Корпоративная облигация",
            sector="Энергетика",
        )
    )
    monkeypatch.setattr(module, "_fetch_asset_metadata_from_api", api)

    enrich_bond_detail_metadata(bond, "token")
    enrich_bond_detail_metadata(bond, "token")

    api.assert_called_once()
