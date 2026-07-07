"""Trading application service — thin facade over use cases."""

from __future__ import annotations

from datetime import date

from bond_monitor.application.trading.attach_use_case import AttachUseCase
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.order_use_case import OrderUseCase, block_non_api_tradable_pending
from bond_monitor.application.trading.sandbox_use_case import SandboxUseCase
from bond_monitor.application.trading.sync_use_case import SyncUseCase
from bond_monitor.application.trading.types import OrderPreviewResult, TradingSyncResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PutOfferDecision
from bond_monitor.domain.portfolio.planner import PortfolioPlan
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord
from bond_monitor.interfaces.schemas.api import PendingOperationResponse


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
        self._sync = SyncUseCase(ctx)
        self._order = OrderUseCase(ctx, self._sync)
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
    ) -> dict:
        return await self._attach.get_account_preview(
            portfolio_id,
            account_id=account_id,
            kind=kind,
        )

    async def clear_account_for_attach(
        self,
        portfolio_id: str,
        *,
        account_id: str,
        kind: AccountKind,
        pay_in_rub: float | None = None,
    ) -> dict:
        return await self._attach.clear_account_for_attach(
            portfolio_id,
            account_id=account_id,
            kind=kind,
            pay_in_rub=pay_in_rub,
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

    async def sync_portfolio(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
        skip_auto_top_up: bool = False,
        reuse_plan: PortfolioPlan | None = None,
    ) -> TradingSyncResult:
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            skip_auto_top_up=skip_auto_top_up,
            reuse_plan=reuse_plan,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
        )

    async def get_pending_operations(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> list[PendingOperationResponse]:
        return await self._sync.get_pending_operations(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
        )

    async def preview_pending_operation(
        self,
        portfolio_id: str,
        op_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
        lots: int | None = None,
        price_pct: float | None = None,
    ) -> OrderPreviewResult:
        return await self._order.preview_pending_operation(
            portfolio_id,
            op_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            lots=lots,
            price_pct=price_pct,
        )

    async def confirm_pending_operation(
        self,
        portfolio_id: str,
        op_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
        lots: int | None = None,
        price_pct: float | None = None,
    ) -> TradingSyncResult:
        return await self._order.confirm_pending_operation(
            portfolio_id,
            op_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            lots=lots,
            price_pct=price_pct,
        )

    async def cancel_pending_order(
        self,
        portfolio_id: str,
        op_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingSyncResult:
        return await self._order.cancel_pending_order(
            portfolio_id,
            op_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def set_put_offer_decision(
        self,
        portfolio_id: str,
        isin: str,
        decision: PutOfferDecision,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingSyncResult:
        return await self._order.set_put_offer_decision(
            portfolio_id,
            isin,
            decision,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def cancel_top_up_batch_operation(
        self,
        portfolio_id: str,
        batch_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingSyncResult:
        return await self._order.cancel_top_up_batch_operation(
            portfolio_id,
            batch_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def get_performance(self, portfolio_id: str) -> dict | None:
        return await self._sync.get_performance(portfolio_id)

    async def get_account_operations_history(self, portfolio_id: str) -> list[OperationRecord]:
        return await self._sync.get_account_operations_history(portfolio_id)
