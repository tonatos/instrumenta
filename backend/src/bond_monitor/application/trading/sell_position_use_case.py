"""Queue manual_sell for sandbox position disposal."""

from __future__ import annotations

import logging
from datetime import date

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.sync_use_case import SyncUseCase
from bond_monitor.application.trading.types import SellPositionPreviewResult, SellQuoteResult, TradingSyncResult
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import PortfolioPosition
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, order_amount_rub
from bond_monitor.domain.trading.policies import (
    format_buy_limit_buffer_label,
    sell_limit_price_buffer,
    suggested_sell_limit_price_pct,
)
from bond_monitor.domain.trading.ports import BrokerSnapshot
from bond_monitor.domain.trading.sell_position import (
    dismiss_queued_manual_sell,
    dismiss_queued_pending,
    find_sellable_position,
    queue_manual_sell,
    validate_sell_request,
)
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot

logger = logging.getLogger(__name__)


def _position_instrument_uid(snapshot: BrokerSnapshot, figi: str | None) -> str:
    if not figi:
        return ""
    broker_pos = snapshot.bond_positions.get(figi)
    return broker_pos.instrument_uid if broker_pos is not None else ""


def _market_price_pct(
    position: PortfolioPosition,
    bond: BondRecord | None,
    snapshot: BrokerSnapshot,
) -> float:
    if position.figi:
        broker_pos = snapshot.bond_positions.get(position.figi)
        if broker_pos is not None and broker_pos.current_price_pct is not None:
            return float(broker_pos.current_price_pct)
    if bond is not None and bond.last_price is not None and bond.last_price > 0:
        return bond.last_price
    return position.purchase_clean_price_pct


def _suggested_sell_price_pct(
    position: PortfolioPosition,
    bond: BondRecord | None,
    snapshot: BrokerSnapshot,
    buffer: float,
) -> tuple[float, float]:
    market = _market_price_pct(position, bond, snapshot)
    suggested = float(suggested_sell_limit_price_pct(market, buffer))
    return market, suggested


def _pricing_context(
    position: PortfolioPosition,
    bond: BondRecord | None,
    snapshot: AccountSnapshot,
    broker_snapshot: BrokerSnapshot,
) -> tuple[float, int, float]:
    face_value = bond.face_value if bond else position.face_value
    lot_size = bond.lot_size if bond else position.lot_size
    aci_rub = (bond.accrued_interest or 0.0) if bond else 0.0
    if not aci_rub and position.figi:
        broker_pos = broker_snapshot.bond_positions.get(position.figi)
        if broker_pos is not None and broker_pos.current_nkd_rub is not None:
            aci_rub = float(broker_pos.current_nkd_rub)
    return face_value, lot_size, aci_rub


class SellPositionUseCase:
    def __init__(self, ctx: TradingContext, sync: SyncUseCase) -> None:
        self._ctx = ctx
        self._sync = sync

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
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        position = find_sellable_position(portfolio, isin)
        available_lots = validate_sell_request(portfolio, position, lots)

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        bond = next((b for b in universe if b.isin == isin), None)
        face_value, lot_size, aci_rub = _pricing_context(
            position, bond, snapshot, broker_snapshot
        )
        buffer = sell_limit_price_buffer(portfolio.account_kind)
        market, suggested = _suggested_sell_price_pct(position, bond, broker_snapshot, buffer)

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

        if position.figi:
            instrument_uid = _position_instrument_uid(broker_snapshot, position.figi)
            broker_preview = broker.preview_order_price(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=position.figi,
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

        position = find_sellable_position(portfolio, isin)
        actual = position.actual_lots if position.actual_lots is not None else 0
        if actual <= 0:
            raise ValueError("На счёте нет лотов для продажи")

        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
        bond = next((b for b in universe if b.isin == isin), None)
        buffer = sell_limit_price_buffer(portfolio.account_kind)
        market, suggested = _suggested_sell_price_pct(position, bond, broker_snapshot, buffer)

        return SellQuoteResult(
            market_price_pct=market,
            suggested_price_pct=suggested,
            available_lots=actual,
            sell_buffer_label=format_buy_limit_buffer_label(buffer),
        )

    async def queue_manual_sell(
        self,
        portfolio_id: str,
        isin: str,
        universe: list[BondRecord],
        *,
        lots: int,
        price_pct: float | None,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingSyncResult:
        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        position = find_sellable_position(portfolio, isin)

        resolved_price = price_pct
        if resolved_price is None:
            token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
            account_id = portfolio.account_id  # type: ignore[assignment]
            snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
            broker_snapshot = broker_snapshot_from_infrastructure(snapshot)
            bond = next((b for b in universe if b.isin == isin), None)
            buffer = sell_limit_price_buffer(portfolio.account_kind)
            _, resolved_price = _suggested_sell_price_pct(
                position, bond, broker_snapshot, buffer
            )

        queue_manual_sell(portfolio, position, lots=lots, price_pct=resolved_price)
        await self._ctx.repo.save(portfolio)
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def dismiss_pending_operation(
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
        dismiss_queued_pending(portfolio, op_id)
        await self._ctx.repo.save(portfolio)
        return await self._sync.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )

    async def dismiss_manual_sell(
        self,
        portfolio_id: str,
        op_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> TradingSyncResult:
        return await self.dismiss_pending_operation(
            portfolio_id,
            op_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )
