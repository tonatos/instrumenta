"""Sell position preview and quote from broker snapshot."""

from __future__ import annotations

import logging
from datetime import date

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.types import SellPositionPreviewResult, SellQuoteResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, order_amount_rub
from bond_monitor.domain.trading.advisory import build_holdings
from bond_monitor.domain.trading.policies import (
    format_buy_limit_buffer_label,
    sell_limit_price_buffer,
    suggested_sell_limit_price_pct,
)
from bond_monitor.domain.trading.ports import BrokerSnapshot
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker

logger = logging.getLogger(__name__)


def _position_instrument_uid(snapshot: BrokerSnapshot, figi: str | None) -> str:
    if not figi:
        return ""
    broker_pos = snapshot.bond_positions.get(figi)
    return broker_pos.instrument_uid if broker_pos is not None else ""


def _find_holding_lots(snapshot: BrokerSnapshot, universe: list[BondRecord], isin: str) -> tuple[str | None, int]:
    bond = next((b for b in universe if b.isin == isin), None)
    if bond and bond.figi:
        pos = snapshot.bond_positions.get(bond.figi)
        if pos is not None:
            return bond.figi, pos.lots
    for figi, pos in snapshot.bond_positions.items():
        holding = next((h for h in build_holdings(snapshot, universe) if h.figi == figi), None)
        if holding and holding.isin == isin:
            return figi, pos.lots
    return None, 0


def _market_price_pct(
    bond: BondRecord | None,
    snapshot: BrokerSnapshot,
    figi: str | None,
    *,
    fallback: float = 100.0,
) -> float:
    if figi:
        broker_pos = snapshot.bond_positions.get(figi)
        if broker_pos is not None and broker_pos.current_price_pct is not None:
            return float(broker_pos.current_price_pct)
    if bond is not None and bond.last_price is not None and bond.last_price > 0:
        return bond.last_price
    return fallback


class SellPositionUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx

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
        del today
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        figi, available_lots = _find_holding_lots(broker_snapshot, universe, isin)
        if available_lots <= 0:
            raise ValueError("На счёте нет лотов для продажи")
        if lots > available_lots:
            raise ValueError(f"Недостаточно лотов: доступно {available_lots}")

        bond = next((b for b in universe if b.isin == isin), None)
        broker_pos = broker_snapshot.bond_positions.get(figi) if figi else None
        face_value = bond.face_value if bond else 1000.0
        lot_size = bond.lot_size if bond else (
            max(1, broker_pos.quantity // max(broker_pos.lots, 1)) if broker_pos else 1
        )
        aci_rub = (bond.accrued_interest or 0.0) if bond else 0.0
        if not aci_rub and broker_pos is not None and broker_pos.current_nkd_rub is not None:
            aci_rub = float(broker_pos.current_nkd_rub)
        buffer = sell_limit_price_buffer(portfolio.account_kind)
        market = _market_price_pct(bond, broker_snapshot, figi)
        suggested = float(suggested_sell_limit_price_pct(market, buffer))

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

        if figi:
            instrument_uid = _position_instrument_uid(broker_snapshot, figi)
            broker_preview = broker.preview_order_price(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=figi,
                instrument_uid=instrument_uid,
                direction="SELL",
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

        return SellPositionPreviewResult(
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
            money_rub=float(snapshot.money_rub),
            sufficient_cash=True,
            preview_source=preview_source,
            available_lots=available_lots,
            sufficient_lots=lots <= available_lots,
            suggested_price_pct=suggested,
        )

    async def get_sell_quote(
        self,
        portfolio_id: str,
        isin: str,
        universe: list[BondRecord],
    ) -> SellQuoteResult:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        figi, available_lots = _find_holding_lots(broker_snapshot, universe, isin)
        if available_lots <= 0:
            raise ValueError("На счёте нет лотов для продажи")

        bond = next((b for b in universe if b.isin == isin), None)
        buffer = sell_limit_price_buffer(portfolio.account_kind)
        market = _market_price_pct(bond, broker_snapshot, figi)
        suggested = float(suggested_sell_limit_price_pct(market, buffer))

        return SellQuoteResult(
            market_price_pct=market,
            suggested_price_pct=suggested,
            available_lots=available_lots,
            sell_buffer_label=format_buy_limit_buffer_label(buffer),
        )
