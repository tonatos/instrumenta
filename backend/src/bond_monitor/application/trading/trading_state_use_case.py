"""Combined trading plan + advice in a single broker I/O round-trip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bond_monitor.application.trading.advise_use_case import AdviseUseCase
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.plan_from_broker import build_trading_plan
from bond_monitor.application.trading.types import TradingAdviceResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.planner import PortfolioPlan
from bond_monitor.domain.portfolio.policies import DurationPolicy
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.snapshot_adapter import (
    broker_active_orders_from_infrastructure,
    broker_operations_from_infrastructure,
    broker_snapshot_from_infrastructure,
)
from bond_monitor.application.trading.advise_use_case import operations_from_date


@dataclass(frozen=True)
class TradingStateResult:
    plan: PortfolioPlan
    advice: TradingAdviceResult


class TradingStateUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx
        self._advise = AdviseUseCase(ctx)

    async def get_trading_state(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
        duration_policy: DurationPolicy | None = None,
    ) -> TradingStateResult:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        operations = broker.get_account_operations(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id=account_id,
            from_date=operations_from_date(portfolio, today=today),
        )
        active_orders = broker.get_active_orders(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id=account_id,
        )

        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        plan = build_trading_plan(
            portfolio,
            broker_snapshot,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            duration_policy=duration_policy,
        )
        advice = await self._advise.build_advice_result(
            portfolio,
            universe,
            snapshot=snapshot,
            operations=operations,
            active_orders=active_orders,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            duration_policy=duration_policy,
        )
        return TradingStateResult(plan=plan, advice=advice)
