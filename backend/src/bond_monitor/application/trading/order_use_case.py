"""Order preview, place and cancel — explicit parameters, no pending queue."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.types import OrderPreviewResult, PlaceOrderResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub, order_amount_rub
from bond_monitor.domain.trading.models import OrderDirection
from bond_monitor.domain.trading.policies import reference_market_price_pct
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.trading_client import (
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


def _resolve_figi(
    token: str,
    *,
    isin: str,
    figi: str | None,
    direction: OrderDirection,
    snapshot,
) -> tuple[str, str]:
    instrument_uid = _position_instrument_uid(snapshot, figi)
    trade = broker.ensure_order_instrument(
        token,
        figi=figi,
        instrument_uid=instrument_uid,
        isin=isin,
        direction=direction,
    )
    resolved_figi = trade.figi or figi
    if not resolved_figi:
        raise ValueError(f"FIGI not found for {isin}")
    return resolved_figi, trade.instrument_uid


def _available_lots_for_sell(snapshot, figi: str | None) -> int:
    if not figi:
        return 0
    pos = snapshot.bond_positions.get(figi)
    return pos.lots if pos is not None else 0


class OrderUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx

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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)

        bond = next((b for b in universe if b.isin == isin), None)
        order_figi = figi or (bond.figi if bond else None)
        broker_pos = broker_snapshot.bond_positions.get(order_figi) if order_figi else None

        face_value = bond.face_value if bond else 1000.0
        lot_size = bond.lot_size if bond else (
            max(1, broker_pos.quantity // max(broker_pos.lots, 1)) if broker_pos else 1
        )
        aci_rub = (bond.accrued_interest or 0.0) if bond else 0.0
        if not aci_rub and broker_pos is not None and broker_pos.current_nkd_rub is not None:
            aci_rub = float(broker_pos.current_nkd_rub)

        clean_amount_rub = round(
            lots * lot_size * face_value * float(price_pct) / 100.0,
            2,
        )
        local_total = round(
            float(
                order_amount_rub(
                    price_pct=PriceUnitPct(price_pct),
                    face_value=face_value,
                    lot_size=lot_size,
                    lots=Lots(lots),
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

        if order_figi:
            instrument_uid = _position_instrument_uid(broker_snapshot, order_figi)
            broker_preview = broker.preview_order_price(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=order_figi,
                instrument_uid=instrument_uid,
                direction=direction,
                lots=Lots(lots),
                price_pct=PriceUnitPct(price_pct),
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
            available = _available_lots_for_sell(broker_snapshot, order_figi)
            sufficient_cash = lots <= available
        else:
            sufficient_cash = money_rub + 0.01 >= required_cash

        broker_current_price = (
            float(broker_pos.current_price_pct)
            if broker_pos is not None and broker_pos.current_price_pct is not None
            else None
        )
        market_price_pct = reference_market_price_pct(
            bond_last_price=bond.last_price if bond else None,
            broker_current_price_pct=broker_current_price,
        )

        return OrderPreviewResult(
            order_lots=lots,
            order_bonds=lots * lot_size,
            lot_size=lot_size,
            order_price_pct=float(price_pct),
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
            market_price_pct=market_price_pct,
            face_value_rub=face_value,
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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        if lots <= 0:
            raise ValueError("Invalid lots")
        if price_pct <= 0:
            raise ValueError("Price is required")

        bond = next((b for b in universe if b.isin == isin), None)
        resolved_figi = figi or (bond.figi if bond else None)

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)

        if direction == "SELL":
            available = _available_lots_for_sell(broker_snapshot, resolved_figi)
            if lots > available:
                raise ValueError(f"Недостаточно лотов на счёте: доступно {available}")

        try:
            order_figi, instrument_uid = _resolve_figi(
                token,
                isin=isin,
                figi=resolved_figi,
                direction=direction,
                snapshot=broker_snapshot,
            )
        except TradingNotAvailableError as exc:
            raise ValueError(str(exc)) from exc

        face_value = bond.face_value if bond else 1000.0
        lot_size = bond.lot_size if bond else 1
        aci_rub = (bond.accrued_interest or 0.0) if bond else 0.0
        if not aci_rub:
            broker_pos = broker_snapshot.bond_positions.get(order_figi)
            if broker_pos is not None and broker_pos.current_nkd_rub is not None:
                aci_rub = float(broker_pos.current_nkd_rub)

        estimated = order_amount_rub(
            price_pct=PriceUnitPct(price_pct),
            face_value=face_value,
            lot_size=lot_size,
            lots=Lots(lots),
            aci_rub=aci_rub,
        )

        idempotency_key = suggestion_id or f"{isin}:{direction}:{lots}"
        request_uid = broker.make_request_uid(
            account_id=account_id,
            figi=order_figi,
            direction=direction,
            lots=lots,
            order_key=idempotency_key,
            salt=datetime.now(UTC).isoformat(timespec="seconds"),
        )

        try:
            result = broker.post_limit_order(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=order_figi,
                instrument_uid=instrument_uid,
                direction=direction,
                lots=Lots(lots),
                price_pct=PriceUnitPct(price_pct),
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

        return PlaceOrderResult(
            order_id=result.order_id,
            status=result.execution_report_status,
            request_uid=request_uid,
            lots_requested=lots,
            lots_executed=result.lots_executed,
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
        )

    async def cancel_order(
        self,
        portfolio_id: str,
        order_id: str,
    ) -> None:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]
        broker.cancel_order(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id=account_id,
            order_id=order_id,
        )
