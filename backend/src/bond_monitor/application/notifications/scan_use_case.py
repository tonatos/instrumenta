"""Scan trading portfolios and deliver notification alerts."""

from __future__ import annotations

import logging
from datetime import date

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.notifications.deliver_use_case import DeliverNotificationsUseCase
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.domain.notifications.rules import WORKER_ALERT_RULES, collect_alerts
from bond_monitor.domain.portfolio.models import PortfolioMode
from bond_monitor.domain.portfolio.risk_monitor import sync_risk_baselines
from bond_monitor.domain.trading.advisory import build_holdings, effective_trading_positions
from bond_monitor.infrastructure.moex.defaults_client import (
    apply_defaults_from_cache,
    refresh_defaults_for_isins,
)
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker

logger = logging.getLogger(__name__)


class ScanPortfoliosUseCase:
    def __init__(
        self,
        *,
        trading_ctx: TradingContext,
        bond_service: BondService,
        deliver: DeliverNotificationsUseCase,
    ) -> None:
        self._trading_ctx = trading_ctx
        self._bond_service = bond_service
        self._deliver = deliver

    async def run(self, *, today: date | None = None) -> int:
        scan_date = today or date.today()
        portfolios = [
            portfolio
            for portfolio in await self._trading_ctx.repo.list_all()
            if portfolio.mode == PortfolioMode.TRADING
            and portfolio.account_id
            and portfolio.account_kind
        ]
        delivered = 0
        portfolio_names: dict[str, str] = {}
        for portfolio in portfolios:
            try:
                delivered += await self._scan_portfolio(
                    portfolio,
                    today=scan_date,
                    portfolio_names=portfolio_names,
                )
            except Exception:
                logger.exception("Portfolio scan failed for %s", portfolio.id)
        await self._deliver.retry_pending(portfolio_names=portfolio_names)
        return delivered

    async def _scan_portfolio(
        self,
        portfolio,
        *,
        today: date,
        portfolio_names: dict[str, str],
    ) -> int:
        portfolio_names[portfolio.id] = portfolio.name
        token = self._trading_ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]
        snapshot = broker.get_account_snapshot(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id,
        )
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        holdings = build_holdings(broker_snapshot, [])
        holding_isins = {h.isin for h in holdings if h.isin}
        if not holding_isins:
            return 0

        universe = self._bond_service.load_by_isins(sorted(holding_isins))
        universe_by_isin = {bond.isin: bond for bond in universe}
        held_bonds = [universe_by_isin[isin] for isin in holding_isins if isin in universe_by_isin]

        refresh_defaults_for_isins(sorted(holding_isins))
        apply_defaults_from_cache(held_bonds)
        changed = sync_risk_baselines(
            portfolio.risk_baselines,
            holding_isins=holding_isins,
            universe_by_isin=universe_by_isin,
        )
        if changed:
            portfolio.touch()
            await self._trading_ctx.repo.save(portfolio)

        holdings = build_holdings(broker_snapshot, universe)
        positions = effective_trading_positions(
            portfolio,
            broker_snapshot,
            universe,
            purchase_date=today,
        )
        alerts = collect_alerts(
            portfolio,
            holdings=holdings,
            positions=positions,
            universe=universe,
            today=today,
            rules=WORKER_ALERT_RULES,
        )
        for alert in alerts:
            await self._deliver.process_alert(alert, portfolio_name=portfolio.name)
        return len(alerts)
