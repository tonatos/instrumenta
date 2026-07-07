"""Broker account ports — domain types without infrastructure dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.shared.money import PriceUnitPct, Rub


@dataclass(frozen=True)
class BrokerBondPosition:
    figi: str
    instrument_uid: str
    ticker: str
    quantity: int
    lots: int
    blocked: int
    current_price_pct: PriceUnitPct | None
    current_nkd_rub: Rub | None
    average_price_pct: PriceUnitPct | None


@dataclass(frozen=True)
class BrokerOtherInstrument:
    instrument_type: str
    figi: str
    ticker: str
    quantity: int


@dataclass(frozen=True)
class BrokerSnapshot:
    account_id: str
    account_kind: AccountKind
    money_rub: Rub
    bond_positions: dict[str, BrokerBondPosition]
    other_instruments: list[BrokerOtherInstrument]
    fetched_at: str
    blocked_money_rub: Rub = Rub(0.0)

    @property
    def has_foreign_instruments(self) -> bool:
        return bool(self.other_instruments)

    @property
    def available_money_rub(self) -> Rub:
        return Rub(max(0.0, float(self.money_rub) - float(self.blocked_money_rub)))


@dataclass(frozen=True)
class BrokerOperation:
    id: str
    type: str
    state: str
    date: datetime
    figi: str
    instrument_uid: str
    instrument_type: str
    payment_rub: Rub | None
    quantity: int
    price_pct: PriceUnitPct | None
    commission_rub: Rub | None


@dataclass(frozen=True)
class BrokerActiveOrder:
    """Активная заявка на счёте брокера (NEW / PARTIALLYFILL)."""

    order_id: str
    request_uid: str
    figi: str
    direction: str
    lots_requested: int
    lots_executed: int
    status: str
    price_pct: float | None
    total_order_amount_rub: float | None
    initial_commission_rub: float | None
