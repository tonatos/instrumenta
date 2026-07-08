"""Trading application service — thin facade over use cases."""

from __future__ import annotations

from datetime import date

from bond_monitor.application.trading.advise_use_case import AdviseUseCase
from bond_monitor.application.trading.attach_use_case import AttachUseCase
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.order_use_case import OrderUseCase
from bond_monitor.application.trading.sandbox_use_case import SandboxUseCase
from bond_monitor.application.trading.sell_position_use_case import SellPositionUseCase
from bond_monitor.application.trading.types import (
    OrderPreviewResult,
    PlaceOrderResult,
    SellPositionPreviewResult,
    SellQuoteResult,
    TradingAdviceResult,
)
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.trading.models import AccountKind, OrderDirection
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord


class TradingService:
    """Trading mode operations."""

    def __init__(
        self,
        repo: PortfolioRepository,
        *,
        sandbox_token: str,
        production_token: str,
    ) -> None:
        ctx = TradingContext(repo, sandbox_token=sandbox_token, production_token=production_token)
        self._attach = AttachUseCase(ctx)
        self._advise = AdviseUseCase(ctx)
        self._order = OrderUseCase(ctx)
        self._sell = SellPositionUseCase(ctx)
        self._sandbox = SandboxUseCase(ctx)

    async def list_accounts(self, kind: AccountKind) -> list[dict]:
        return await self._sandbox.list_accounts(kind)

    async def delete_sandbox_account(self, account_id: str) -> dict:
        return await self._sandbox.delete_sandbox_account(account_id)

    async def sandbox_pay_in_for_portfolio(self, portfolio_id: str, *, amount_rub: float) -> dict:
        return await self._sandbox.sandbox_pay_in_for_portfolio(portfolio_id, amount_rub=amount_rub)

    async def create_sandbox_account(
        self,
        *,
        initial_amount_rub: float,
        name: str | None = None,
    ) -> dict:
        return await self._sandbox.create_sandbox_account(
            initial_amount_rub=initial_amount_rub,
            name=name,
        )

    async def get_account_preview(
        self,
        portfolio_id: str,
        *,
        account_id: str,
        kind: AccountKind,
        universe: list[BondRecord],
    ) -> dict:
        return await self._attach.get_account_preview(
            portfolio_id,
            account_id=account_id,
            kind=kind,
            universe=universe,
        )

    async def clear_account_for_attach(
        self,
        portfolio_id: str,
        *,
        account_id: str,
        kind: AccountKind,
        pay_in_rub: float | None = None,
        universe: list[BondRecord] | None = None,
    ) -> dict:
        return await self._attach.clear_account_for_attach(
            portfolio_id,
            account_id=account_id,
            kind=kind,
            pay_in_rub=pay_in_rub,
            universe=universe,
        )

    async def attach_account(
        self,
        portfolio_id: str,
        *,
        account_id: str,
        kind: AccountKind,
        universe: list[BondRecord],
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> Portfolio:
        return await self._attach.attach_account(
            portfolio_id,
            account_id=account_id,
            kind=kind,
            universe=universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def detach_account(self, portfolio_id: str) -> Portfolio:
        return await self._attach.detach_account(portfolio_id)

    async def get_advice(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingAdviceResult:
        return await self._advise.get_advice(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def preview_order(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        isin: str,
        direction: OrderDirection,
        lots: int,
        price_pct: float,
        figi: str | None = None,
    ) -> OrderPreviewResult:
        return await self._order.preview_order(
            portfolio_id,
            universe,
            isin=isin,
            direction=direction,
            lots=lots,
            price_pct=price_pct,
            figi=figi,
        )

    async def place_order(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        isin: str,
        direction: OrderDirection,
        lots: int,
        price_pct: float,
        figi: str | None = None,
        suggestion_id: str | None = None,
    ) -> PlaceOrderResult:
        return await self._order.place_order(
            portfolio_id,
            universe,
            isin=isin,
            direction=direction,
            lots=lots,
            price_pct=price_pct,
            figi=figi,
            suggestion_id=suggestion_id,
        )

    async def cancel_order(self, portfolio_id: str, order_id: str) -> None:
        await self._order.cancel_order(portfolio_id, order_id)

    async def preview_sell_position(
        self,
        portfolio_id: str,
        isin: str,
        universe: list[BondRecord],
        *,
        lots: int,
        price_pct: float,
        today: date,
    ) -> SellPositionPreviewResult:
        return await self._sell.preview_sell_position(
            portfolio_id,
            isin,
            universe,
            lots=lots,
            price_pct=price_pct,
            today=today,
        )

    async def get_sell_quote(
        self,
        portfolio_id: str,
        isin: str,
        universe: list[BondRecord],
    ) -> SellQuoteResult:
        return await self._sell.get_sell_quote(portfolio_id, isin, universe)

    async def get_performance(self, portfolio_id: str) -> dict | None:
        return await self._advise.get_performance(portfolio_id)

    async def get_account_operations_history(self, portfolio_id: str) -> list[OperationRecord]:
        return await self._advise.get_account_operations_history(portfolio_id)
