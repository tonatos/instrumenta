"""Shared helpers for sandbox integration tests."""

from __future__ import annotations

from dataclasses import dataclass

from bond_monitor.domain.shared.money import PriceUnitPct


@dataclass(frozen=True)
class LiquidOfz:
    figi: str
    isin: str
    last_price_pct: PriceUnitPct
    lot_size: int
    face_value: float


def find_liquid_ofz(token: str) -> LiquidOfz | None:
    """Find first liquid OFZ with a non-zero last price."""
    from t_tech.invest import Client, InstrumentStatus
    from t_tech.invest.sandbox.client import SandboxClient

    candidates: list = []
    with SandboxClient(token) as sandbox_client:
        bonds_resp = sandbox_client.instruments.bonds(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
        )
        for bond in bonds_resp.instruments:
            if "ОФЗ" not in (bond.name or ""):
                continue
            if not bond.api_trade_available_flag or not bond.buy_available_flag:
                continue
            candidates.append(bond)
            if len(candidates) >= 30:
                break

        for bond in candidates:
            prices_resp = sandbox_client.market_data.get_last_prices(figi=[bond.figi])
            for entry in prices_resp.last_prices:
                p = entry.price
                units = int(getattr(p, "units", 0))
                nano = int(getattr(p, "nano", 0))
                if units == 0 and nano == 0:
                    continue
                price_pct = float(units) + nano / 1_000_000_000.0
                fv = bond.nominal
                fv_value = float(getattr(fv, "units", 0)) + (
                    int(getattr(fv, "nano", 0)) / 1_000_000_000.0
                )
                return LiquidOfz(
                    figi=bond.figi,
                    isin=bond.isin,
                    last_price_pct=PriceUnitPct(price_pct),
                    lot_size=int(bond.lot or 1),
                    face_value=fv_value or 1000.0,
                )

    with Client(token) as client:
        for bond in candidates:
            prices_resp = client.market_data.get_last_prices(figi=[bond.figi])
            for entry in prices_resp.last_prices:
                p = entry.price
                units = int(getattr(p, "units", 0))
                nano = int(getattr(p, "nano", 0))
                if units == 0 and nano == 0:
                    continue
                price_pct = float(units) + nano / 1_000_000_000.0
                fv = bond.nominal
                fv_value = float(getattr(fv, "units", 0)) + (
                    int(getattr(fv, "nano", 0)) / 1_000_000_000.0
                )
                return LiquidOfz(
                    figi=bond.figi,
                    isin=bond.isin,
                    last_price_pct=PriceUnitPct(price_pct),
                    lot_size=int(bond.lot or 1),
                    face_value=fv_value or 1000.0,
                )
    return None
