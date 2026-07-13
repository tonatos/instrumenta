"""Shared Litestar DI providers for API controllers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.application.portfolio.portfolio_service import PortfolioService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.infrastructure.persistence.deploy_session_repository import DeploySessionRepository
from bond_monitor.interfaces.config import Settings


async def provide_portfolio_service(db_session: AsyncSession) -> PortfolioService:
    return PortfolioService(PortfolioRepository(db_session))


async def provide_trading_service(
    db_session: AsyncSession,
    settings: Settings,
) -> TradingService:
    repo = PortfolioRepository(db_session)
    return TradingService(
        repo,
        DeploySessionRepository(db_session),
        sandbox_token=settings.t_trading_token_sandbox,
        production_token=settings.t_trading_token_production,
    )
