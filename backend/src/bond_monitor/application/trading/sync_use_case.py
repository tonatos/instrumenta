"""Portfolio sync with broker account."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.types import TradingSyncResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.portfolio.planner import PortfolioPlan, build_plan, distribute_top_up
from bond_monitor.domain.trading.broker_orders import reconcile_active_broker_orders
from bond_monitor.domain.trading.cash_constraints import available_cash_for_new_purchases_rub
from bond_monitor.domain.trading.pending_operations import (
    api_trade_position_warnings,
    compute_pending_operations,
    sweep_completed_pending,
    sweep_non_api_tradable_pending,
)
from bond_monitor.domain.trading.position_lifecycle import (
    apply_filled_reinvest_buys,
    close_matured_positions,
)
from bond_monitor.domain.trading.reconciler import detect_top_up, reconcile_positions
from bond_monitor.domain.trading.top_up import (
    apply_top_up_distribution,
    has_active_top_up_batch,
    new_top_up_batch_id,
)
from bond_monitor.domain.trading.yield_calc import summarize_actual_performance
from bond_monitor.infrastructure.tinvest.snapshot_adapter import (
    broker_active_orders_from_infrastructure,
    broker_operations_from_infrastructure,
    broker_snapshot_from_infrastructure,
)
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.trading_client import (
    OperationRecord,
    TradingClientError,
)
from bond_monitor.interfaces.schemas.api import PendingOperationResponse

logger = logging.getLogger(__name__)


def _operations_from_date(portfolio: Portfolio, *, today: date) -> date:
    if portfolio.trading_started_at:
        try:
            return datetime.fromisoformat(portfolio.trading_started_at).date()
        except ValueError:
            logger.warning("Invalid trading_started_at: %s", portfolio.trading_started_at)
    return today - timedelta(days=365)


def _refresh_position_figis_from_universe(
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> None:
    for pos in portfolio.positions:
        bond = universe_by_isin.get(pos.isin)
        if bond and bond.figi:
            pos.figi = bond.figi


def _pending_to_response(ops) -> list[PendingOperationResponse]:
    return [PendingOperationResponse.model_validate(op.to_dict()) for op in ops]


class SyncUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx

    def _refresh_trade_record_states(self, portfolio: Portfolio, token: str) -> int:
        if not portfolio.account_id or not portfolio.account_kind:
            return 0
        updated = 0
        for tr in portfolio.trade_records:
            if not tr.is_active or not tr.order_id:
                continue
            try:
                state = broker.get_order_state(
                    token,
                    portfolio.account_kind,
                    account_id=portfolio.account_id,
                    order_id=tr.order_id,
                )
                if state.execution_report_status != tr.status:
                    tr.status = state.execution_report_status
                    updated += 1
                if state.lots_executed != tr.lots_executed:
                    tr.lots_executed = state.lots_executed
                    updated += 1
                if state.total_order_amount_rub is not None:
                    new_total = float(state.total_order_amount_rub)
                    if tr.total_order_amount_rub != new_total:
                        tr.total_order_amount_rub = new_total
                        updated += 1
                tr.last_state_checked_at = datetime.now(UTC).isoformat(timespec="seconds")
            except TradingClientError as exc:
                logger.warning("Failed to refresh order %s: %s", tr.order_id, exc)
        return updated

    def _import_active_broker_orders(
        self,
        portfolio: Portfolio,
        token: str,
        *,
        universe_by_isin: dict[str, BondRecord],
    ) -> int:
        if not portfolio.account_id or not portfolio.account_kind:
            return 0
        try:
            infra_orders = broker.get_active_orders(
                token,
                portfolio.account_kind,
                account_id=portfolio.account_id,
            )
        except TradingClientError as exc:
            logger.warning("Failed to fetch active broker orders: %s", exc)
            return 0
        broker_orders = broker_active_orders_from_infrastructure(infra_orders)
        return reconcile_active_broker_orders(
            portfolio,
            broker_orders,
            universe_by_isin=universe_by_isin,
        )

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
        block_non_api_tradable_pending=None,
    ) -> TradingSyncResult:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        try:
            infra_snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
            infra_operations = broker.get_account_operations(
                token,
                portfolio.account_kind,
                account_id,  # type: ignore[arg-type]
                from_date=_operations_from_date(portfolio, today=today),
            )
        except TradingClientError as exc:
            raise ValueError(str(exc)) from exc

        snapshot = broker_snapshot_from_infrastructure(infra_snapshot)
        operations = broker_operations_from_infrastructure(infra_operations)
        universe_by_isin = {b.isin: b for b in universe}

        reconciliation = reconcile_positions(portfolio, snapshot, operations)
        self._import_active_broker_orders(portfolio, token, universe_by_isin=universe_by_isin)
        self._refresh_trade_record_states(portfolio, token)
        apply_filled_reinvest_buys(portfolio, universe_by_isin, today)
        close_matured_positions(portfolio, snapshot, today)
        sweep_completed_pending(portfolio)
        _refresh_position_figis_from_universe(portfolio, universe_by_isin)
        sweep_non_api_tradable_pending(portfolio, universe_by_isin)
        api_trade_warnings = api_trade_position_warnings(portfolio, universe_by_isin)

        top_up = detect_top_up(portfolio, operations, snapshot)
        top_up_auto_applied = False
        top_up_distributed_rub = 0.0
        top_up_notes: list[str] = []

        if (
            top_up.has_pending_top_up
            and not has_active_top_up_batch(portfolio)
            and not skip_auto_top_up
        ):
            free_cash = available_cash_for_new_purchases_rub(
                float(snapshot.money_rub),
                portfolio,
                universe_by_isin,
            )
            amount = min(float(top_up.available_for_distribution_rub), free_cash)
            allocations, dist_notes = distribute_top_up(
                portfolio=portfolio,
                universe=universe,
                top_up_amount_rub=amount,
                today=today,
                key_rate=key_rate,
                tax_rate=tax_rate,
            )
            if allocations:
                batch_id = new_top_up_batch_id()
                processed_at = datetime.now(UTC).isoformat()
                distributed = sum(a.estimated_amount_rub for a in allocations)
                apply_notes = apply_top_up_distribution(
                    portfolio,
                    allocations,
                    distributed_amount_rub=distributed,
                    batch_id=batch_id,
                    processed_at_iso=processed_at,
                    universe_by_isin=universe_by_isin,
                    today=today,
                )
                top_up_auto_applied = True
                top_up_distributed_rub = distributed
                top_up_notes = [*dist_notes, *apply_notes]

        plan = reuse_plan
        if plan is None or top_up_auto_applied:
            plan = build_plan(
                portfolio,
                universe,
                today=today,
                key_rate=key_rate,
                tax_rate=tax_rate,
                account_snapshot_money_rub=snapshot.money_rub,
                assume_best_put_outcome=False,
            )

        pending = compute_pending_operations(
            portfolio,
            snapshot,
            today,
            universe=universe,
            resolved_slots=plan.resolved_slots,
        )
        if block_non_api_tradable_pending is not None:
            block_non_api_tradable_pending(portfolio, token, pending, infra_snapshot)

        top_up_after = detect_top_up(portfolio, operations, snapshot)
        portfolio.touch()
        await self._ctx.repo.save(portfolio)

        return TradingSyncResult(
            pending_operations=_pending_to_response(pending),
            drifts=[
                {
                    "isin": d.isin,
                    "name": d.name,
                    "expected_lots": d.expected_lots,
                    "actual_lots": d.actual_lots,
                    "severity": d.severity,
                    "message": d.message,
                }
                for d in reconciliation.drifts
            ],
            money_rub=float(snapshot.money_rub),
            last_synced_at=portfolio.last_synced_at,
            has_pending_top_up=top_up_after.has_pending_top_up,
            pending_top_up_rub=float(top_up_after.pending_top_up_rub),
            top_up_auto_applied=top_up_auto_applied,
            top_up_distributed_rub=top_up_distributed_rub,
            top_up_notes=top_up_notes,
            notes=[*plan.notes, *top_up_notes, *api_trade_warnings],
        )

    async def get_pending_operations(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
        block_non_api_tradable_pending=None,
    ) -> list[PendingOperationResponse]:
        result = await self.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
        )
        return result.pending_operations

    async def get_performance(self, portfolio_id: str) -> dict | None:
        portfolio = await self._ctx.repo.get_by_id(portfolio_id)
        if portfolio is None or not portfolio.account_id or not portfolio.account_kind:
            return None
        token = self._ctx.token(portfolio.account_kind)
        today = date.today()
        operations = broker.get_account_operations(
            token,
            portfolio.account_kind,
            portfolio.account_id,
            from_date=_operations_from_date(portfolio, today=today),
        )
        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, portfolio.account_id)
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        broker_operations = broker_operations_from_infrastructure(operations)
        perf = summarize_actual_performance(portfolio, broker_snapshot, broker_operations)
        return {
            "xirr_pct": perf.xirr_pct,
            "coupons_received_rub": float(perf.coupons_received_rub),
            "tax_paid_rub": float(perf.tax_paid_rub),
            "money_rub": float(snapshot.money_rub),
        }

    async def get_account_operations_history(
        self,
        portfolio_id: str,
    ) -> list[OperationRecord]:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        today = date.today()
        operations = broker.get_account_operations(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            portfolio.account_id,  # type: ignore[arg-type]
            from_date=_operations_from_date(portfolio, today=today),
        )
        return sorted(operations, key=lambda op: op.date, reverse=True)
