"""BondService unit tests."""

from __future__ import annotations

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.infrastructure.tinvest.read_client import CouponPayment


def test_load_by_secid_enriches_issuer_metadata_when_token_present(monkeypatch) -> None:
    bond = BondRecord(secid="TEST", isin="RU000ATEST", name="Газпром001", asset_uid="asset-1")
    detail_calls: list[BondRecord] = []

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.fetch_bond_by_secid",
        lambda secid: bond if secid == "TEST" else None,
    )
    monkeypatch.setattr(
        BondService,
        "_enrich_and_score",
        lambda self, bonds: (bonds, "MOEX ISS API"),
    )

    def fake_enrich_detail(target: BondRecord, token: str) -> None:
        detail_calls.append(target)
        target.issuer_name = "ПАО Газпром"
        target.description = "Корпоративная облигация"

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.enrich_bond_detail_metadata",
        fake_enrich_detail,
    )

    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="read-token")
    loaded = service.load_by_secid("TEST")

    assert loaded is bond
    assert detail_calls == [bond]
    assert loaded.issuer_name == "ПАО Газпром"
    assert loaded.description == "Корпоративная облигация"


def test_load_by_secid_skips_issuer_metadata_without_token(monkeypatch) -> None:
    bond = BondRecord(secid="TEST", isin="RU000ATEST", name="Газпром001", asset_uid="asset-1")

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.fetch_bond_by_secid",
        lambda secid: bond,
    )
    monkeypatch.setattr(
        BondService,
        "_enrich_and_score",
        lambda self, bonds: (bonds, "MOEX ISS API"),
    )

    def fail_enrich_detail(*_args, **_kwargs) -> None:
        raise AssertionError("enrich_bond_detail_metadata should not be called without token")

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.enrich_bond_detail_metadata",
        fail_enrich_detail,
    )

    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="")
    loaded = service.load_by_secid("TEST")

    assert loaded is bond
    assert loaded.issuer_name == ""


def test_get_coupon_schedule_passes_token_before_figi(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_get_bond_coupon_schedule(token: str, figi: str, days_ahead: int = 365):
        calls.append((token, figi))
        return [
            CouponPayment(
                payment_date=None,
                amount_rub=42.5,
                coupon_type_raw=2,
            )
        ]

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.get_bond_coupon_schedule",
        fake_get_bond_coupon_schedule,
    )

    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="read-token")
    result = service.get_coupon_schedule("bond-figi")

    assert calls == [("read-token", "bond-figi")]
    assert result == [
        {"payment_date": None, "amount_rub": 42.5, "coupon_type_raw": 2},
    ]


def test_get_coupon_schedule_skips_without_token() -> None:
    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="")
    assert service.get_coupon_schedule("bond-figi") == []


def test_load_universe_uses_in_memory_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_fetch_all_bonds_unfiltered():
        calls["count"] += 1
        return []

    def fake_enrich_and_score(self, bonds):
        return bonds, "MOEX ISS API"

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.fetch_all_bonds_unfiltered",
        fake_fetch_all_bonds_unfiltered,
    )
    monkeypatch.setattr(BondService, "_enrich_and_score", fake_enrich_and_score)

    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="")
    first = service.load_universe()
    second = service.load_universe()

    assert calls["count"] == 1
    assert first is second
