"""Attach and detach broker accounts to portfolios."""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioMode
from bond_monitor.domain.portfolio.planner import build_plan
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.domain.trading.advisory import AttachPreviewValidation, validate_attach_soft
from bond_monitor.domain.trading.models import AccountKind, FrozenForecast
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    TradingClientError,
)

logger = logging.getLogger(__name__)

_CLEAR_POLL_ATTEMPTS = 15
_CLEAR_POLL_INTERVAL_SEC = 0.3


def _reset_sandbox_account(
    token: str,
    account_id: str,
    portfolio: Portfolio,
    _snapshot: AccountSnapshot,
    *,
    pay_in_rub: float | None = None,
) -> tuple[str, str, Rub]:
    pay_in = Rub(pay_in_rub if pay_in_rub is not None else portfolio.initial_amount_rub)
    broker.close_sandbox_account(token, account_id)
    new_id = broker.open_sandbox_account(token, name="bond-monitor-cleared")
    broker.sandbox_pay_in(token, new_id, pay_in)
    return account_id, new_id, pay_in


def _snapshot_to_preview(
    snapshot: AccountSnapshot,
    validation: AttachPreviewValidation,
    *,
    linked_portfolio: Portfolio | None = None,
) -> dict:
    return {
        "money_rub": float(snapshot.money_rub),
        "bond_positions": [
            {
                "figi": pos.figi,
                "ticker": pos.ticker,
                "quantity": pos.quantity,
                "lots": pos.lots,
                "current_price_pct": (
                    float(pos.current_price_pct) if pos.current_price_pct is not None else None
                ),
            }
            for pos in snapshot.bond_positions.values()
        ],
        "other_instruments": [
            {
                "instrument_type": ins.instrument_type,
                "ticker": ins.ticker,
                "figi": ins.figi,
                "quantity": ins.quantity,
            }
            for ins in snapshot.other_instruments
        ],
        "has_securities": bool(snapshot.bond_positions or snapshot.other_instruments),
        "can_attach": validation.can_attach,
        "blockers": list(validation.blockers),
        "warnings": list(validation.warnings),
        "linked_portfolio": (
            {"id": linked_portfolio.id, "name": linked_portfolio.name}
            if linked_portfolio is not None
            else None
        ),
    }


def _with_account_linkage_validation(
    validation: AttachPreviewValidation,
    linked_portfolio: Portfolio | None,
) -> AttachPreviewValidation:
    if linked_portfolio is None:
        return validation
    blocker = (
        f"Счёт уже привязан к портфелю «{linked_portfolio.name}». "
        "Отвяжите его там или выберите другой счёт."
    )
    return AttachPreviewValidation(
        can_attach=False,
        blockers=[blocker, *validation.blockers],
        warnings=list(validation.warnings),
        effective_initial_amount_rub=validation.effective_initial_amount_rub,
    )


class AttachUseCase:
    def __init__(self, ctx: TradingContext) -> None:
        self._ctx = ctx

    async def get_account_preview(
        self,
        portfolio_id: str,
        *,
        account_id: str,
        kind: AccountKind,
        universe: list[BondRecord],
    ) -> dict:
        portfolio = await self._ctx.repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        snapshot = broker.get_account_snapshot(self._ctx.token(kind), kind, account_id)
        linked_portfolio = await self._ctx.find_linked_portfolio(
            account_id=account_id,
            kind=kind,
            exclude_portfolio_id=portfolio_id,
        )
        validation = _with_account_linkage_validation(
            validate_attach_soft(
                broker_snapshot_from_infrastructure(snapshot),
                portfolio,
                universe,
            ),
            linked_portfolio,
        )
        return _snapshot_to_preview(
            snapshot,
            validation,
            linked_portfolio=linked_portfolio,
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
        if kind != AccountKind.SANDBOX:
            raise ValueError("Освобождение счёта доступно только в песочнице")

        portfolio = await self._ctx.repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")

        token = self._ctx.token(kind)
        snapshot = broker.get_account_snapshot(token, kind, account_id)
        sold: list[dict] = []
        sell_failed = False
        active_account_id = account_id

        for figi, pos in list(snapshot.bond_positions.items()):
            if pos.lots <= 0:
                continue

            label = pos.ticker or figi[:8]
            trade = broker.check_trade_available(token, figi, instrument_uid=pos.instrument_uid)
            if trade is not None:
                sell_figi = trade.figi or figi
                sell_uid = trade.instrument_uid or pos.instrument_uid
            else:
                sell_figi = figi
                sell_uid = pos.instrument_uid
            lot_size = (
                trade.lot_size if trade is not None else max(1, pos.quantity // max(1, pos.lots))
            )

            reference_price = pos.current_price_pct
            if reference_price is None and trade is not None:
                last_price = broker.get_last_price_pct(token, trade.figi or figi)
                if last_price is not None:
                    reference_price = PriceUnitPct(last_price)

            request_uid = broker.make_request_uid(
                account_id=active_account_id,
                figi=figi,
                direction="SELL",
                lots=pos.lots,
                order_key=f"clear-account:{figi}",
                salt=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            try:
                result = broker.post_market_sell_order(
                    token,
                    kind,
                    account_id=active_account_id,
                    figi=sell_figi,
                    instrument_uid=sell_uid,
                    lots=Lots(pos.lots),
                    request_uid=request_uid,
                    reference_price_pct=reference_price,
                    lot_size=lot_size,
                )
            except TradingClientError:
                logger.warning("Sandbox clear: sell failed for %s, will reset account", label)
                sell_failed = True
                break
            sold.append(
                {
                    "figi": figi,
                    "ticker": pos.ticker,
                    "lots": pos.lots,
                    "order_id": result.order_id,
                    "status": result.execution_report_status,
                }
            )

        reset_note: str | None = None
        account_replaced: dict[str, str] | None = None

        if not sell_failed:
            for _ in range(_CLEAR_POLL_ATTEMPTS):
                snapshot = broker.get_account_snapshot(token, kind, active_account_id)
                if not snapshot.bond_positions:
                    break
                time.sleep(_CLEAR_POLL_INTERVAL_SEC)

        if sell_failed or snapshot.bond_positions or snapshot.other_instruments:
            old_id, new_id, paid = _reset_sandbox_account(
                token,
                active_account_id,
                portfolio,
                snapshot,
                pay_in_rub=pay_in_rub,
            )
            active_account_id = new_id
            account_replaced = {"old_id": old_id, "new_id": new_id}
            reset_note = (
                "Не удалось продать бумаги через API песочницы — счёт пересоздан "
                f"с пополнением {float(paid):,.0f} ₽. Привяжите новый счёт."
            )
            snapshot = broker.get_account_snapshot(token, kind, active_account_id)
            sold = []

        linked_portfolio = await self._ctx.find_linked_portfolio(
            account_id=active_account_id,
            kind=kind,
            exclude_portfolio_id=portfolio_id,
        )
        validation = _with_account_linkage_validation(
            validate_attach_soft(
                broker_snapshot_from_infrastructure(snapshot),
                portfolio,
                universe or [],
            ),
            linked_portfolio,
        )
        preview = _snapshot_to_preview(
            snapshot,
            validation,
            linked_portfolio=linked_portfolio,
        )
        preview["sold_count"] = len(sold)
        preview["sold"] = sold
        preview["account_id"] = active_account_id
        if account_replaced is not None:
            preview["account_replaced"] = account_replaced
        if reset_note is not None:
            preview["reset_note"] = reset_note
        return preview

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
        portfolio = await self._ctx.repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        linked_portfolio = await self._ctx.find_linked_portfolio(
            account_id=account_id,
            kind=kind,
            exclude_portfolio_id=portfolio_id,
        )
        if linked_portfolio is not None:
            raise ValueError(
                f"Счёт уже привязан к портфелю «{linked_portfolio.name}». "
                "Отвяжите его там или выберите другой счёт."
            )
        token = self._ctx.token(kind)
        snapshot = broker.get_account_snapshot(token, kind, account_id)
        validation = validate_attach_soft(
            broker_snapshot_from_infrastructure(snapshot),
            portfolio,
            universe,
        )
        portfolio.initial_amount_rub = float(validation.effective_initial_amount_rub)
        for pos in portfolio.positions:
            if not pos.figi:
                pos.figi = broker.resolve_figi_for_isin(token, pos.isin) or ""
        plan = build_plan(
            portfolio,
            universe,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            account_snapshot_money_rub=snapshot.money_rub,
            assume_best_put_outcome=False,
        )
        now_iso = datetime.now(UTC).isoformat(timespec="seconds")
        portfolio.mode = PortfolioMode.TRADING
        portfolio.account_id = account_id
        portfolio.account_kind = kind
        portfolio.trading_started_at = now_iso
        portfolio.frozen_forecast = FrozenForecast(
            expected_xirr_pct=plan.effective_annual_return_pct,
            expected_total_net_profit_rub=plan.total_net_profit_rub,
            expected_final_value_rub=plan.final_portfolio_value_rub,
            frozen_initial_amount_rub=portfolio.initial_amount_rub,
            horizon_date=portfolio.horizon_date,
        )
        return await self._ctx.repo.save(portfolio)

    async def detach_account(self, portfolio_id: str) -> Portfolio:
        portfolio = await self._ctx.repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        portfolio.mode = PortfolioMode.SIMULATION
        portfolio.account_id = None
        portfolio.account_kind = None
        portfolio.frozen_forecast = None
        portfolio.trading_started_at = None
        return await self._ctx.repo.save(portfolio)
