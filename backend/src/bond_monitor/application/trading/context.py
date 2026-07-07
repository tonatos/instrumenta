"""Shared dependencies for trading use cases."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import Portfolio, PortfolioMode
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository


class TradingContext:
    """Repository access and token resolution for trading use cases."""

    def __init__(
        self,
        repo: PortfolioRepository,
        *,
        sandbox_token: str,
        production_token: str,
    ) -> None:
        self._repo = repo
        self._sandbox_token = sandbox_token
        self._production_token = production_token

    @property
    def repo(self) -> PortfolioRepository:
        return self._repo

    def token(self, kind: AccountKind) -> str:
        token = self._sandbox_token if kind == AccountKind.SANDBOX else self._production_token
        if not token:
            raise ValueError(f"Trading token for {kind.value} not configured")
        return token

    async def get_trading_portfolio(self, portfolio_id: str) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        if not portfolio.is_trading or not portfolio.account_id or not portfolio.account_kind:
            raise ValueError("Portfolio is not in trading mode")
        return portfolio

    async def find_linked_portfolio(
        self,
        *,
        account_id: str,
        kind: AccountKind,
        exclude_portfolio_id: str | None = None,
    ) -> Portfolio | None:
        for portfolio in await self._repo.list_all():
            if portfolio.mode != PortfolioMode.TRADING:
                continue
            if portfolio.account_id != account_id:
                continue
            if portfolio.account_kind != kind:
                continue
            if exclude_portfolio_id and portfolio.id == exclude_portfolio_id:
                continue
            return portfolio
        return None
