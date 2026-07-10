"""Trading risk monitoring orchestration — MOEX refresh and baseline sync."""

from __future__ import annotations

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.portfolio.risk_monitor import sync_risk_baselines
from bond_monitor.infrastructure.moex.defaults_client import (
    apply_defaults_from_cache,
    refresh_defaults_for_isins,
)


async def prepare_trading_risk_monitoring(
    ctx: TradingContext,
    portfolio: Portfolio,
    universe: list[BondRecord],
    holding_isins: set[str],
) -> None:
    """Refresh MOEX defaults for holdings, sync baselines, persist if needed."""
    if holding_isins:
        refresh_defaults_for_isins(sorted(holding_isins))

    universe_by_isin = {bond.isin: bond for bond in universe}
    held_bonds = [universe_by_isin[isin] for isin in holding_isins if isin in universe_by_isin]
    apply_defaults_from_cache(held_bonds)

    changed = sync_risk_baselines(
        portfolio.risk_baselines,
        holding_isins=holding_isins,
        universe_by_isin=universe_by_isin,
    )
    if changed:
        portfolio.touch()
        await ctx.repo.save(portfolio)


async def acknowledge_trading_risk(
    ctx: TradingContext,
    portfolio: Portfolio,
    isin: str,
    universe: list[BondRecord],
) -> None:
    """Accept current risk state as new baseline for a held ISIN."""
    bond = next((b for b in universe if b.isin == isin), None)
    if bond is None:
        raise ValueError(f"Bond {isin} not found in market universe")
    apply_defaults_from_cache([bond])
    from bond_monitor.domain.portfolio.risk_monitor import acknowledge_risk_baseline

    acknowledge_risk_baseline(portfolio.risk_baselines, isin, bond)
    portfolio.touch()
    await ctx.repo.save(portfolio)
