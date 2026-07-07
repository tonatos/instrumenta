"""BondService unit tests."""

from __future__ import annotations

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.infrastructure.tinvest.read_client import CouponPayment


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
