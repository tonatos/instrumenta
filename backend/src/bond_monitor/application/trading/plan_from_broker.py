"""Build portfolio plan from live broker snapshot (trading mode)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from dataclasses import replace

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.portfolio.planner import PortfolioPlan, build_plan
from bond_monitor.domain.trading.advisory import effective_trading_positions
from bond_monitor.domain.trading.ports import BrokerSnapshot


def build_trading_plan(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    universe: Sequence[BondRecord],
    *,
    key_rate: float,
    tax_rate: float,
    today: date,
) -> PortfolioPlan:
    """План портфеля в TRADING: позиции и кэш — live со счёта брокера."""
    positions = effective_trading_positions(
        portfolio,
        snapshot,
        universe,
        purchase_date=today,
    )
    ephemeral = replace(portfolio, positions=positions)
    return build_plan(
        ephemeral,
        universe,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        assume_best_put_outcome=False,
        account_snapshot_money_rub=snapshot.money_rub,
    )
