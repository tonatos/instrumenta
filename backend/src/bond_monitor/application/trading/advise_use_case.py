"""Stateless trading advice from broker snapshot + market."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.types import (
    ActiveOrderResponse,
    HoldingResponse,
    PerformanceResponse,
    SuggestionResponse,
    TradingAdviceResult,
)
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.trading.advisory import advise
from bond_monitor.infrastructure.tinvest.snapshot_adapter import (
    broker_active_orders_from_infrastructure,
    broker_operations_from_infrastructure,
    broker_snapshot_from_infrastructure,
)
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord

_OPERATIONS_LOOKBACK_DAYS = 365


def operations_from_date(portfolio, *, today: date) -> date:
    """Нижняя граница истории операций — полный год, не момент attach."""
    del portfolio
    return today - timedelta(days=_OPERATIONS_LOOKBACK_DAYS)


def _holding_to_response(h) -> HoldingResponse:
    return HoldingResponse(
        figi=h.figi,
        isin=h.isin,
        name=h.name,
        lots=h.lots,
        quantity=h.quantity,
        lot_size=h.lot_size,
        current_price_pct=h.current_price_pct,
        current_nkd_rub=h.current_nkd_rub,
        ytm=h.ytm,
        maturity_date=h.maturity_date.isoformat() if h.maturity_date else None,
        offer_date=h.offer_date.isoformat() if h.offer_date else None,
        market_value_rub=h.market_value_rub,
    )


def _suggestion_to_response(s) -> SuggestionResponse:
    return SuggestionResponse(
        id=s.id,
        kind=s.kind,
        isin=s.isin,
        name=s.name,
        lots=s.lots,
        figi=s.figi,
        suggested_price_pct=s.suggested_price_pct,
        market_price_pct=s.market_price_pct,
        reason=s.reason,
        due_date=s.due_date.isoformat() if s.due_date else None,
        source_isin=s.source_isin,
        chat_template=s.chat_template,
        urgency=s.urgency,
    )


def _active_order_to_response(o) -> ActiveOrderResponse:
    return ActiveOrderResponse(
        order_id=o.order_id,
        request_uid=o.request_uid,
        figi=o.figi,
        direction=o.direction,
        lots_requested=o.lots_requested,
        lots_executed=o.lots_executed,
        status=o.status,
        price_pct=o.price_pct,
        total_order_amount_rub=o.total_order_amount_rub,
        initial_commission_rub=o.initial_commission_rub,
    )


def _cashflow_to_dict(event) -> dict:
    return {
        "date": event.date.isoformat(),
        "kind": event.kind,
        "amount_rub": event.amount_rub,
        "description": event.description,
        "related_isin": event.related_isin,
        "is_projected": event.is_projected,
        "lots": event.lots,
        "bonds_count": event.bonds_count,
    }


class AdviseUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx

    async def get_advice(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingAdviceResult:
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
        return self.build_advice_result(
            portfolio,
            universe,
            snapshot=snapshot,
            operations=operations,
            active_orders=active_orders,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    def build_advice_result(
        self,
        portfolio,
        universe: list[BondRecord],
        *,
        snapshot,
        operations,
        active_orders,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingAdviceResult:
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)

        advice = advise(
            portfolio,
            broker_snapshot,
            broker_active_orders_from_infrastructure(active_orders),
            broker_operations_from_infrastructure(operations),
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

        performance = None
        if advice.performance is not None:
            perf = advice.performance
            performance = PerformanceResponse(
                xirr_pct=perf.xirr_pct,
                coupons_received_rub=float(perf.coupons_received_rub),
                tax_paid_rub=float(perf.tax_paid_rub),
                commission_paid_rub=float(perf.commission_paid_rub),
                realized_profit_rub=float(perf.realized_profit_rub),
                unrealized_value_rub=float(perf.unrealized_value_rub),
                invested_rub=float(perf.invested_rub),
                received_rub=float(perf.received_rub),
                as_of=perf.as_of,
            )

        return TradingAdviceResult(
            holdings=[_holding_to_response(h) for h in advice.holdings],
            cashflow=[_cashflow_to_dict(e) for e in advice.cashflow],
            performance=performance,
            suggestions=[_suggestion_to_response(s) for s in advice.suggestions],
            active_orders=[_active_order_to_response(o) for o in advice.active_orders],
            money_rub=advice.money_rub,
            available_money_rub=advice.available_money_rub,
            blocked_money_rub=advice.blocked_money_rub,
            warnings=list(advice.warnings),
            as_of=advice.as_of,
        )

    async def get_performance(self, portfolio_id: str) -> dict | None:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]
        today = date.today()

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        operations = broker.get_account_operations(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id=account_id,
            from_date=operations_from_date(portfolio, today=today),
        )
        from bond_monitor.domain.trading.advisory import build_holdings, holdings_to_positions

        holdings = build_holdings(broker_snapshot, [])
        universe_by_isin: dict[str, BondRecord] = {}
        positions = holdings_to_positions(holdings, universe_by_isin, purchase_date=today)
        perf_portfolio = portfolio
        perf_portfolio.positions = positions  # ephemeral for yield calc

        from bond_monitor.domain.trading.yield_calc import summarize_actual_performance

        perf = summarize_actual_performance(
            perf_portfolio,
            broker_snapshot,
            broker_operations_from_infrastructure(operations),
        )
        return {
            "xirr_pct": perf.xirr_pct,
            "coupons_received_rub": float(perf.coupons_received_rub),
            "tax_paid_rub": float(perf.tax_paid_rub),
            "money_rub": float(snapshot.money_rub),
        }

    async def get_account_operations_history(self, portfolio_id: str) -> list[OperationRecord]:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]
        return sorted(
            broker.get_account_operations(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                from_date=operations_from_date(portfolio, today=date.today()),
            ),
            key=lambda op: op.date,
            reverse=True,
        )
