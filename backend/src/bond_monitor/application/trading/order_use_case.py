"""Order preview, confirm, cancel and put-offer decisions."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.sync_use_case import SyncUseCase
from bond_monitor.application.trading.types import OrderPreviewResult, TradingSyncResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PutOfferDecision
from bond_monitor.domain.portfolio.planner import build_plan
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub, order_amount_rub
from bond_monitor.domain.trading.models import OrderDirection, PendingOperation, TradeRecord
from bond_monitor.domain.trading.pending_operations import compute_pending_operations
from bond_monitor.domain.trading.position_lifecycle import (
    ensure_reinvest_position,
    find_reinvest_slot_for_op,
    reinvest_source_for_slot,
)
from bond_monitor.domain.trading.top_up import cancel_top_up_batch
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    OrderTooLargeError,
    TradingClientError,
    TradingNotAvailableError,
)

logger = logging.getLogger(__name__)


def _position_instrument_uid(snapshot, figi: str | None) -> str:
    if not figi:
        return ""
    broker_pos = snapshot.bond_positions.get(figi)
    return broker_pos.instrument_uid if broker_pos is not None else ""


def _instrument_trade_cache_key(isin: str, direction: str) -> str:
    return f"{isin.upper()}:{direction}"


def _store_instrument_trade_cache(
    portfolio: Portfolio,
    *,
    isin: str,
    direction: str,
    api_tradable: bool,
    figi: str | None,
    block_reason: str | None = None,
) -> None:
    portfolio.instrument_trade_cache[_instrument_trade_cache_key(isin, direction)] = {
        "api_tradable": api_tradable,
        "figi": figi,
        "block_reason": block_reason,
    }


def block_non_api_tradable_pending(
    portfolio: Portfolio,
    token: str,
    pending: list[PendingOperation],
    snapshot: AccountSnapshot,
) -> None:
    """Пометить pending-операции недоступными для API-торговли до клика «Подтвердить»."""
    broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
    for op in pending:
        if op.status in ("in_progress", "blocked"):
            continue
        if op.kind == "put_offer_submit":
            continue
        direction = "SELL" if op.kind == "manual_sell" else "BUY"
        cache_key = _instrument_trade_cache_key(op.isin, direction)
        cached = portfolio.instrument_trade_cache.get(cache_key)
        if cached is not None:
            if cached.get("api_tradable"):
                if cached.get("figi"):
                    op.figi = str(cached["figi"])
                continue
            op.status = "blocked"
            op.block_reason = str(cached.get("block_reason") or "Operation is blocked")
            op.urgency = "normal"
            continue
        try:
            trade = broker.ensure_order_instrument(
                token,
                figi=op.figi,
                instrument_uid=_position_instrument_uid(broker_snapshot, op.figi),
                isin=op.isin,
                direction=direction,  # type: ignore[arg-type]
            )
        except TradingNotAvailableError as exc:
            _store_instrument_trade_cache(
                portfolio,
                isin=op.isin,
                direction=direction,
                api_tradable=False,
                figi=op.figi,
                block_reason=str(exc),
            )
            op.status = "blocked"
            op.block_reason = str(exc)
            op.urgency = "normal"
        except ValueError:
            pass
        else:
            resolved_figi = trade.figi or op.figi
            _store_instrument_trade_cache(
                portfolio,
                isin=op.isin,
                direction=direction,
                api_tradable=True,
                figi=resolved_figi,
            )
            if resolved_figi:
                op.figi = resolved_figi


def _order_request_uid(
    portfolio: Portfolio,
    *,
    account_id: str,
    figi: str,
    direction: OrderDirection,
    lots: int,
    pending_op_id: str,
) -> str:
    terminal = {
        "EXECUTION_REPORT_STATUS_CANCELLED",
        "EXECUTION_REPORT_STATUS_REJECTED",
    }
    prior_attempts = sum(
        1
        for tr in portfolio.trade_records
        if tr.pending_op_id == pending_op_id and tr.status in terminal
    )
    salt = f"retry-{prior_attempts}" if prior_attempts else ""
    return broker.make_request_uid(
        account_id=account_id,
        figi=figi,
        direction=direction,
        lots=lots,
        pending_op_id=pending_op_id,
        salt=salt,
    )


class OrderUseCase:
    def __init__(self, ctx: TradingContext, sync: SyncUseCase) -> None:
        self._ctx = ctx
        self._sync = sync

    def _find_pending_op(
        self,
        portfolio: Portfolio,
        snapshot,
        universe: list[BondRecord],
        today: date,
        op_id: str,
        *,
        resolved_slots,
    ) -> PendingOperation | None:
        pending = compute_pending_operations(
            portfolio,
            snapshot,
            today,
            universe=universe,
            resolved_slots=resolved_slots,
        )
        for op in pending:
            if op.id == op_id:
                return op
        return None

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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        plan = build_plan(
            portfolio,
            universe,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            account_snapshot_money_rub=snapshot.money_rub,
            assume_best_put_outcome=False,
        )
        op = self._find_pending_op(
            portfolio,
            broker_snapshot,
            universe,
            today,
            op_id,
            resolved_slots=plan.resolved_slots,
        )
        if op is None:
            raise ValueError(f"Pending operation {op_id} not found or already completed")
        if op.kind == "put_offer_submit":
            raise ValueError("Put-offer operations cannot be previewed via order API")
        if op.status == "in_progress":
            raise ValueError("Order already submitted and is in progress")
        if op.status == "blocked":
            raise ValueError(op.block_reason or "Operation is blocked")

        direction: OrderDirection = "SELL" if op.kind == "manual_sell" else "BUY"

        order_lots = lots if lots is not None else op.lots
        order_price = price_pct if price_pct is not None else op.suggested_price_pct
        if order_lots is None or order_lots <= 0:
            raise ValueError("Invalid lots")
        if order_price is None:
            raise ValueError("Price is required")

        bond = next((b for b in universe if b.isin == op.isin), None)
        face_value = bond.face_value if bond else (op.face_value_rub or 1000.0)
        lot_size = bond.lot_size if bond else (op.lot_size or 1)
        aci_rub = (bond.accrued_interest or 0.0) if bond else (op.aci_rub_per_bond or 0.0)
        if not aci_rub and op.figi:
            broker_pos = broker_snapshot.bond_positions.get(op.figi)
            if broker_pos is not None and broker_pos.current_nkd_rub is not None:
                aci_rub = float(broker_pos.current_nkd_rub)

        clean_amount_rub = round(
            order_lots * lot_size * face_value * float(order_price) / 100.0,
            2,
        )
        local_total = round(
            float(
                order_amount_rub(
                    price_pct=PriceUnitPct(order_price),
                    face_value=face_value,
                    lot_size=lot_size,
                    lots=Lots(order_lots),
                    aci_rub=aci_rub,
                )
            ),
            2,
        )

        broker_clean: float | None = None
        broker_aci: float | None = None
        broker_total: float | None = None
        broker_commission: float | None = None
        preview_source = "moex"

        if op.figi:
            instrument_uid = _position_instrument_uid(broker_snapshot, op.figi)
            broker_preview = broker.preview_order_price(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=op.figi,
                instrument_uid=instrument_uid,
                direction=direction,
                lots=Lots(order_lots),
                price_pct=PriceUnitPct(order_price),
                face_value=face_value,
            )
            if broker_preview is not None:
                preview_source = "broker"
                if broker_preview.clean_amount_rub is not None:
                    broker_clean = float(broker_preview.clean_amount_rub)
                if broker_preview.aci_amount_rub is not None:
                    broker_aci = float(broker_preview.aci_amount_rub)
                if broker_preview.total_order_amount_rub is not None:
                    broker_total = float(broker_preview.total_order_amount_rub)
                commissions = [
                    float(v)
                    for v in (
                        broker_preview.deal_commission_rub,
                        broker_preview.executed_commission_rub,
                    )
                    if v is not None
                ]
                broker_commission = round(sum(commissions), 2) if commissions else None

        required_cash = broker_total if broker_total is not None else local_total
        money_rub = float(snapshot.money_rub)
        if direction == "SELL":
            position = next((p for p in portfolio.positions if p.isin == op.isin), None)
            actual = position.actual_lots if position and position.actual_lots is not None else 0
            sufficient_cash = order_lots <= actual
        else:
            sufficient_cash = money_rub + 0.01 >= required_cash

        return OrderPreviewResult(
            order_lots=order_lots,
            order_bonds=order_lots * lot_size,
            lot_size=lot_size,
            order_price_pct=float(order_price),
            clean_amount_rub=clean_amount_rub,
            aci_rub_per_bond=aci_rub,
            local_total_amount_rub=local_total,
            broker_clean_amount_rub=broker_clean,
            broker_aci_amount_rub=broker_aci,
            broker_total_amount_rub=broker_total,
            broker_commission_rub=broker_commission,
            money_rub=money_rub,
            sufficient_cash=sufficient_cash,
            preview_source=preview_source,
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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        plan = build_plan(
            portfolio,
            universe,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            account_snapshot_money_rub=snapshot.money_rub,
            assume_best_put_outcome=False,
        )
        op = self._find_pending_op(
            portfolio,
            broker_snapshot,
            universe,
            today,
            op_id,
            resolved_slots=plan.resolved_slots,
        )
        if op is None:
            raise ValueError(f"Pending operation {op_id} not found or already completed")
        if op.kind == "put_offer_submit":
            raise ValueError("Put-offer operations cannot be confirmed via order API")
        if op.status == "in_progress":
            raise ValueError("Order already submitted and is in progress")
        if op.status == "blocked":
            raise ValueError(op.block_reason or "Operation is blocked")

        direction: OrderDirection = "SELL" if op.kind == "manual_sell" else "BUY"

        order_lots = lots if lots is not None else op.lots
        order_price = price_pct if price_pct is not None else op.suggested_price_pct
        if order_lots is None or order_lots <= 0:
            raise ValueError("Invalid lots")
        if order_price is None:
            raise ValueError("Price is required")

        bond = next((b for b in universe if b.isin == op.isin), None)

        if op.kind == "reinvest_buy":
            slot = find_reinvest_slot_for_op(portfolio, plan.resolved_slots, op)
            if slot is None:
                raise ValueError("Reinvestment slot not found for this operation")
            if bond is None:
                raise ValueError(f"Bond {op.isin} not found in universe")
            ensure_reinvest_position(
                portfolio,
                bond,
                lots=order_lots,
                source=reinvest_source_for_slot(slot),
                figi=op.figi,
                today=today,
                purchase_price_pct=float(order_price),
            )
            await self._ctx.repo.save(portfolio)

        instrument_uid = _position_instrument_uid(broker_snapshot, op.figi)
        try:
            trade = broker.ensure_order_instrument(
                token,
                figi=op.figi,
                instrument_uid=instrument_uid,
                isin=op.isin,
                direction=direction,
            )
        except TradingNotAvailableError as exc:
            raise ValueError(str(exc)) from exc
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        op.figi = trade.figi or op.figi
        _store_instrument_trade_cache(
            portfolio,
            isin=op.isin,
            direction=direction,
            api_tradable=True,
            figi=op.figi,
        )

        if bond is None:
            bond = next((b for b in universe if b.isin == op.isin), None)
        face_value = bond.face_value if bond else 1000.0
        lot_size = bond.lot_size if bond else 1
        aci_rub = (bond.accrued_interest or 0.0) if bond else (op.aci_rub_per_bond or 0.0)
        estimated = order_amount_rub(
            price_pct=PriceUnitPct(order_price),
            face_value=face_value,
            lot_size=lot_size,
            lots=Lots(order_lots),
            aci_rub=aci_rub,
        )

        request_uid = _order_request_uid(
            portfolio,
            account_id=account_id,
            figi=op.figi,
            direction=direction,
            lots=order_lots,
            pending_op_id=op.id,
        )

        try:
            result = broker.post_limit_order(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=op.figi,
                instrument_uid=trade.instrument_uid,
                direction=direction,
                lots=Lots(order_lots),
                price_pct=PriceUnitPct(order_price),
                face_value=face_value,
                request_uid=request_uid,
                estimated_total_amount_rub=estimated,
            )
        except OrderTooLargeError as exc:
            raise ValueError(str(exc)) from exc
        except TradingNotAvailableError as exc:
            raise ValueError(str(exc)) from exc
        except TradingClientError as exc:
            raise ValueError(str(exc)) from exc

        portfolio.trade_records.append(
            TradeRecord(
                request_uid=request_uid,
                account_id=account_id,
                account_kind=portfolio.account_kind,  # type: ignore[arg-type]
                figi=op.figi,
                direction=direction,
                lots=order_lots,
                pending_op_id=op.id,
                order_id=result.order_id,
                price_pct=order_price,
                status=result.execution_report_status,
                total_order_amount_rub=(
                    float(result.total_order_amount_rub)
                    if result.total_order_amount_rub is not None
                    else None
                ),
                initial_commission_rub=(
                    float(result.initial_commission_rub)
                    if result.initial_commission_rub is not None
                    else None
                ),
                lots_executed=result.lots_executed,
            )
        )
        await self._ctx.repo.save(portfolio)
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            reuse_plan=plan,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        active: TradeRecord | None = None
        for tr in portfolio.trade_records:
            if tr.pending_op_id == op_id and tr.is_active and tr.order_id:
                active = tr
                break
        if active is None:
            raise ValueError("No active order found for this operation")

        broker.cancel_order(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id=account_id,
            order_id=active.order_id,  # type: ignore[arg-type]
        )
        active.status = "EXECUTION_REPORT_STATUS_CANCELLED"
        active.last_state_checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        await self._ctx.repo.save(portfolio)
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        found = False
        for pos in portfolio.positions:
            if pos.isin == isin:
                pos.put_offer_decision = decision
                found = True
                break
        if not found:
            raise ValueError(f"Position {isin} not found")
        portfolio.touch()
        await self._ctx.repo.save(portfolio)
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        cancel_top_up_batch(portfolio, batch_id)
        portfolio.touch()
        await self._ctx.repo.save(portfolio)
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            skip_auto_top_up=True,
            block_non_api_tradable_pending=block_non_api_tradable_pending,
        )
