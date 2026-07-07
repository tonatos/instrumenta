"""Sandbox account management use cases."""

from __future__ import annotations

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.domain.portfolio.models import PortfolioMode
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.application.trading import broker


def _linked_portfolio_dict(portfolio) -> dict | None:
    if portfolio is None:
        return None
    return {"id": portfolio.id, "name": portfolio.name}


class SandboxUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx

    async def list_accounts(self, kind: AccountKind) -> list[dict]:
        accounts = broker.list_accounts(self._ctx.token(kind), kind)
        linked_by_account_id = {
            portfolio.account_id: portfolio
            for portfolio in await self._ctx.repo.list_all()
            if (
                portfolio.mode == PortfolioMode.TRADING
                and portfolio.account_id
                and portfolio.account_kind == kind
            )
        }
        return [
            {
                "id": account.id,
                "name": account.name,
                "kind": kind.value,
                "linked_portfolio": _linked_portfolio_dict(
                    linked_by_account_id.get(account.id),
                ),
            }
            for account in accounts
        ]

    async def delete_sandbox_account(self, account_id: str) -> dict:
        kind = AccountKind.SANDBOX
        token = self._ctx.token(kind)
        linked = await self._ctx.find_linked_portfolio(account_id=account_id, kind=kind)
        deleted_portfolio_id: str | None = None
        if linked is not None:
            deleted_portfolio_id = linked.id
            await self._ctx.repo.delete(linked.id)
        broker.close_sandbox_account(token, account_id)
        return {
            "account_id": account_id,
            "deleted_portfolio_id": deleted_portfolio_id,
        }

    async def sandbox_pay_in_for_portfolio(
        self,
        portfolio_id: str,
        *,
        amount_rub: float,
    ) -> dict:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        if portfolio.account_kind != AccountKind.SANDBOX:
            raise ValueError("Пополнение доступно только для песочницы")
        if amount_rub <= 0:
            raise ValueError("Сумма пополнения должна быть больше нуля")
        token = self._ctx.token(AccountKind.SANDBOX)
        balance = broker.sandbox_pay_in(token, portfolio.account_id, Rub(amount_rub))  # type: ignore[arg-type]
        return {
            "amount_added_rub": amount_rub,
            "money_rub": float(balance),
        }

    async def create_sandbox_account(
        self,
        *,
        initial_amount_rub: float,
        name: str | None = None,
    ) -> dict:
        if initial_amount_rub <= 0:
            raise ValueError("Сумма пополнения должна быть больше нуля")
        token = self._ctx.token(AccountKind.SANDBOX)
        account_name = (name or "bond-monitor").strip() or "bond-monitor"
        account_id = broker.open_sandbox_account(token, name=account_name)
        balance = broker.sandbox_pay_in(token, account_id, Rub(initial_amount_rub))
        return {
            "id": account_id,
            "name": account_name,
            "kind": AccountKind.SANDBOX.value,
            "money_rub": float(balance),
        }
