"""Mutable portfolio state projected from simulation events."""

from __future__ import annotations

from dataclasses import dataclass, field

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import PortfolioPosition


@dataclass
class OpenPosition:
    """Tracked open lot with lifecycle metadata."""

    position: PortfolioPosition
    generation: int = 0
    closed: bool = False


@dataclass
class PortfolioState:
    """Write-model snapshot while simulating cashflow."""

    cash: float
    open_positions: list[OpenPosition] = field(default_factory=list)
    all_positions: list[PortfolioPosition] = field(default_factory=list)

    def lots_by_isin(self) -> dict[str, int]:
        lots: dict[str, int] = {}
        for entry in self.open_positions:
            if entry.closed:
                continue
            lots[entry.position.isin] = lots.get(entry.position.isin, 0) + entry.position.lots
        return lots

    def holdings_value(self, universe_by_isin: dict[str, BondRecord]) -> float:
        total = 0.0
        for isin, lots in self.lots_by_isin().items():
            bond = universe_by_isin.get(isin)
            if bond is None:
                continue
            lot_cost = bond.price_per_lot_rub or 0.0
            if lot_cost > 0:
                total += lots * lot_cost
        return total

    def is_open(self, position_id: int) -> bool:
        for entry in self.open_positions:
            if id(entry.position) == position_id:
                return not entry.closed
        return False

    def close_position(self, position_id: int) -> None:
        for entry in self.open_positions:
            if id(entry.position) == position_id:
                entry.closed = True
                return

    def add_position(self, position: PortfolioPosition, *, generation: int) -> OpenPosition:
        entry = OpenPosition(position=position, generation=generation)
        self.open_positions.append(entry)
        self.all_positions.append(position)
        return entry
