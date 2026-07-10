"""Trading holdings read-model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HoldingView:
    """Позиция на счёте, обогащённая рыночными данными."""

    figi: str
    isin: str
    name: str
    lots: int
    quantity: int
    lot_size: int
    current_price_pct: float | None
    current_nkd_rub: float | None
    ytm: float | None
    maturity_date: date | None
    offer_date: date | None
    market_value_rub: float | None
