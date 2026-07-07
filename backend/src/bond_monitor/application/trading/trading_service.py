"""Trading application service."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import (
    AccountKind,
    FrozenForecast,
    OrderDirection,
    PendingOperation,
    Portfolio,
    PortfolioMode,
    PutOfferDecision,
    TradeRecord,
)
from bond_monitor.domain.portfolio.planner import PortfolioPlan, build_plan, distribute_top_up
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub, order_amount_rub
from bond_monitor.domain.trading.cash_constraints import available_cash_for_new_purchases_rub
from bond_monitor.domain.trading.pending_operations import (
    api_trade_position_warnings,
    compute_pending_operations,
    sweep_completed_pending,
    sweep_non_api_tradable_pending,
)
from bond_monitor.domain.trading.reconciler import (
    AttachValidation,
    detect_top_up,
    reconcile_positions,
    validate_account_for_attach,
)
from bond_monitor.domain.trading.top_up import (
    apply_top_up_distribution,
    cancel_top_up_batch,
    has_active_top_up_batch,
    new_top_up_batch_id,
)
from bond_monitor.domain.trading.yield_calc import summarize_actual_performance
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.infrastructure.tinvest.read_client import (
    check_trade_available,
    ensure_order_instrument,
    get_last_price_pct,
    resolve_figi_for_isin,
)
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    OperationRecord,
    OrderTooLargeError,
    TradingClientError,
    TradingNotAvailableError,
    cancel_order,
    close_sandbox_account,
    get_account_operations,
    get_account_snapshot,
    get_order_state,
    list_accounts,
    make_request_uid,
    open_sandbox_account,
    post_limit_order,
    post_market_sell_order,
    preview_order_price,
    sandbox_pay_in,
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
    """Закрыть sandbox-счёт с бумагами и открыть чистый с пополнением."""
    pay_in = Rub(pay_in_rub if pay_in_rub is not None else portfolio.initial_amount_rub)
    close_sandbox_account(token, account_id)
    new_id = open_sandbox_account(token, name="bond-monitor-cleared")
    sandbox_pay_in(token, new_id, pay_in)
    return account_id, new_id, pay_in


def _snapshot_to_preview(
    snapshot: AccountSnapshot,
    validation,
    *,
    linked_portfolio: Portfolio | None = None,
) -> dict:
    preview = {
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
    return preview


def _with_account_linkage_validation(
    validation: AttachValidation,
    linked_portfolio: Portfolio | None,
) -> AttachValidation:
    if linked_portfolio is None:
        return validation
    blocker = (
        f"Счёт уже привязан к портфелю «{linked_portfolio.name}». "
        "Отвяжите его там или выберите другой счёт."
    )
    return AttachValidation(
        can_attach=False,
        blockers=[blocker, *validation.blockers],
        warnings=list(validation.warnings),
        effective_initial_amount_rub=validation.effective_initial_amount_rub,
    )


def _linked_portfolio_dict(portfolio: Portfolio | None) -> dict | None:
    if portfolio is None:
        return None
    return {"id": portfolio.id, "name": portfolio.name}


@dataclass
class TradingSyncResult:
    """Результат синхронизации портфеля со счётом T-Invest."""

    pending_operations: list[dict]
    drifts: list[dict]
    money_rub: float
    last_synced_at: str | None
    has_pending_top_up: bool = False
    pending_top_up_rub: float = 0.0
    top_up_auto_applied: bool = False
    top_up_distributed_rub: float = 0.0
    top_up_notes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class OrderPreviewResult:
    """Превью стоимости заявки до подтверждения."""

    order_lots: int
    order_bonds: int
    lot_size: int
    order_price_pct: float
    clean_amount_rub: float
    aci_rub_per_bond: float
    local_total_amount_rub: float
    broker_clean_amount_rub: float | None
    broker_aci_amount_rub: float | None
    broker_total_amount_rub: float | None
    broker_commission_rub: float | None
    money_rub: float
    sufficient_cash: bool
    preview_source: str = "moex"


def _refresh_position_figis_from_universe(
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> None:
    """Обновить figi позиций из enriched universe (актуальный tradable FIGI)."""
    for pos in portfolio.positions:
        bond = universe_by_isin.get(pos.isin)
        if bond and bond.figi:
            pos.figi = bond.figi


def _operations_from_date(portfolio: Portfolio, *, today: date) -> date:
    """Начало периода для запроса операций у брокера (sync / performance)."""
    if portfolio.trading_started_at:
        try:
            return datetime.fromisoformat(portfolio.trading_started_at).date()
        except ValueError:
            logger.warning("Invalid trading_started_at: %s", portfolio.trading_started_at)
    return today - timedelta(days=365)


def _position_instrument_uid(snapshot: AccountSnapshot, figi: str | None) -> str:
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


def _block_non_api_tradable_pending(
    portfolio: Portfolio,
    token: str,
    pending: list[PendingOperation],
    snapshot: AccountSnapshot,
) -> None:
    """Пометить pending-операции недоступными для API-торговли до клика «Подтвердить»."""
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
            trade = ensure_order_instrument(
                token,
                figi=op.figi,
                instrument_uid=_position_instrument_uid(snapshot, op.figi),
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
    """UID заявки с учётом повторов после отмены/отклонения.

    T-Invest хранит ключ идемпотентности до года: повтор с тем же
    ``order_id`` после отмены даёт 30057. Для каждой новой попытки
    добавляем ``salt`` по числу завершённых (неуспешных) заявок.
    """
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
    return make_request_uid(
        account_id=account_id,
        figi=figi,
        direction=direction,
        lots=lots,
        pending_op_id=pending_op_id,
        salt=salt,
    )


class TradingService:
    """Trading mode operations."""

    def __init__(
        self, repo: PortfolioRepository, *, sandbox_token: str, production_token: str
    ) -> None:
        self._repo = repo
        self._sandbox_token = sandbox_token
        self._production_token = production_token

    def _token(self, kind: AccountKind) -> str:
        token = self._sandbox_token if kind == AccountKind.SANDBOX else self._production_token
        if not token:
            raise ValueError(f"Trading token for {kind.value} not configured")
        return token

    async def _get_trading_portfolio(self, portfolio_id: str) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        if not portfolio.is_trading or not portfolio.account_id or not portfolio.account_kind:
            raise ValueError("Portfolio is not in trading mode")
        return portfolio

    async def _find_linked_portfolio(
        self,
        *,
        account_id: str,
        kind: AccountKind,
        exclude_portfolio_id: str | None = None,
    ) -> Portfolio | None:
        for portfolio in await self._repo.list_all():
            if portfolio.mode != PortfolioMode.TRADING:
                continue
            if portfolio.account_id != account_id:
                continue
            if portfolio.account_kind != kind:
                continue
            if exclude_portfolio_id and portfolio.id == exclude_portfolio_id:
                continue
            return portfolio
        return None

    async def list_accounts(self, kind: AccountKind) -> list[dict]:
        accounts = list_accounts(self._token(kind), kind)
        linked_by_account_id = {
            portfolio.account_id: portfolio
            for portfolio in await self._repo.list_all()
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
        token = self._token(kind)
        linked = await self._find_linked_portfolio(account_id=account_id, kind=kind)
        deleted_portfolio_id: str | None = None
        if linked is not None:
            deleted_portfolio_id = linked.id
            await self._repo.delete(linked.id)
        close_sandbox_account(token, account_id)
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        if portfolio.account_kind != AccountKind.SANDBOX:
            raise ValueError("Пополнение доступно только для песочницы")
        if amount_rub <= 0:
            raise ValueError("Сумма пополнения должна быть больше нуля")
        token = self._token(AccountKind.SANDBOX)
        balance = sandbox_pay_in(token, portfolio.account_id, Rub(amount_rub))  # type: ignore[arg-type]
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
        token = self._token(AccountKind.SANDBOX)
        account_name = (name or "bond-monitor").strip() or "bond-monitor"
        account_id = open_sandbox_account(token, name=account_name)
        balance = sandbox_pay_in(token, account_id, Rub(initial_amount_rub))
        return {
            "id": account_id,
            "name": account_name,
            "kind": AccountKind.SANDBOX.value,
            "money_rub": float(balance),
        }

    async def get_account_preview(
        self,
        portfolio_id: str,
        *,
        account_id: str,
        kind: AccountKind,
    ) -> dict:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        snapshot = get_account_snapshot(self._token(kind), kind, account_id)
        linked_portfolio = await self._find_linked_portfolio(
            account_id=account_id,
            kind=kind,
            exclude_portfolio_id=portfolio_id,
        )
        validation = _with_account_linkage_validation(
            validate_account_for_attach(snapshot, portfolio),
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
    ) -> dict:
        if kind != AccountKind.SANDBOX:
            raise ValueError("Освобождение счёта доступно только в песочнице")

        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")

        token = self._token(kind)
        snapshot = get_account_snapshot(token, kind, account_id)
        sold: list[dict] = []
        sell_failed = False
        active_account_id = account_id

        for figi, pos in list(snapshot.bond_positions.items()):
            if pos.lots <= 0:
                continue

            label = pos.ticker or figi[:8]
            trade = check_trade_available(token, figi, instrument_uid=pos.instrument_uid)
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
                last_price = get_last_price_pct(token, trade.figi or figi)
                if last_price is not None:
                    reference_price = PriceUnitPct(last_price)

            request_uid = make_request_uid(
                account_id=active_account_id,
                figi=figi,
                direction="SELL",
                lots=pos.lots,
                pending_op_id=f"clear-account:{figi}",
                salt=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            try:
                result = post_market_sell_order(
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
                snapshot = get_account_snapshot(token, kind, active_account_id)
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
            snapshot = get_account_snapshot(token, kind, active_account_id)
            sold = []

        linked_portfolio = await self._find_linked_portfolio(
            account_id=active_account_id,
            kind=kind,
            exclude_portfolio_id=portfolio_id,
        )
        validation = _with_account_linkage_validation(
            validate_account_for_attach(snapshot, portfolio),
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
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        linked_portfolio = await self._find_linked_portfolio(
            account_id=account_id,
            kind=kind,
            exclude_portfolio_id=portfolio_id,
        )
        if linked_portfolio is not None:
            raise ValueError(
                f"Счёт уже привязан к портфелю «{linked_portfolio.name}». "
                "Отвяжите его там или выберите другой счёт."
            )
        token = self._token(kind)
        snapshot = get_account_snapshot(token, kind, account_id)
        validation = validate_account_for_attach(snapshot, portfolio)
        if validation.blockers:
            raise ValueError("; ".join(validation.blockers))
        portfolio.initial_amount_rub = float(validation.effective_initial_amount_rub)
        for pos in portfolio.positions:
            if not pos.figi:
                pos.figi = resolve_figi_for_isin(token, pos.isin) or ""
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
        portfolio.last_top_up_processed_at = now_iso
        portfolio.last_synced_at = snapshot.fetched_at
        portfolio.frozen_forecast = FrozenForecast(
            expected_xirr_pct=plan.effective_annual_return_pct,
            expected_total_net_profit_rub=plan.total_net_profit_rub,
            expected_final_value_rub=plan.final_portfolio_value_rub,
            frozen_initial_amount_rub=portfolio.initial_amount_rub,
            horizon_date=portfolio.horizon_date,
        )
        return await self._repo.save(portfolio)

    async def detach_account(self, portfolio_id: str) -> Portfolio:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError("Portfolio not found")
        portfolio.mode = PortfolioMode.SIMULATION
        portfolio.account_id = None
        portfolio.account_kind = None
        portfolio.frozen_forecast = None
        portfolio.trading_started_at = None
        portfolio.last_synced_at = None
        return await self._repo.save(portfolio)

    def _refresh_trade_record_states(self, portfolio: Portfolio, token: str) -> int:
        if not portfolio.account_id or not portfolio.account_kind:
            return 0
        updated = 0
        for tr in portfolio.trade_records:
            if not tr.is_active or not tr.order_id:
                continue
            try:
                state = get_order_state(
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        token = self._token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        try:
            snapshot = get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
            operations = get_account_operations(
                token,
                portfolio.account_kind,
                account_id,  # type: ignore[arg-type]
                from_date=_operations_from_date(portfolio, today=today),
            )
        except TradingClientError as exc:
            raise ValueError(str(exc)) from exc

        reconciliation = reconcile_positions(portfolio, snapshot, operations)
        self._refresh_trade_record_states(portfolio, token)
        sweep_completed_pending(portfolio)
        universe_by_isin = {b.isin: b for b in universe}
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
                processed_at = datetime.now(UTC).isoformat(timespec="seconds")
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
        _block_non_api_tradable_pending(portfolio, token, pending, snapshot)

        top_up_after = detect_top_up(portfolio, operations, snapshot)
        portfolio.touch()
        await self._repo.save(portfolio)

        return TradingSyncResult(
            pending_operations=[op.to_dict() for op in pending],
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
    ) -> list[dict]:
        result = await self.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
        )
        return result.pending_operations

    def _find_pending_op(
        self,
        portfolio: Portfolio,
        snapshot,
        universe: list[BondRecord],
        today: date,
        op_id: str,
        *,
        resolved_slots,
    ):
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        token = self._token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
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
            snapshot,
            universe,
            today,
            op_id,
            resolved_slots=plan.resolved_slots,
        )
        if op is None:
            raise ValueError(f"Pending operation {op_id} not found or already completed")
        if op.kind == "put_offer_submit":
            raise ValueError("Put-offer operations cannot be previewed via order API")
        if op.kind == "manual_sell":
            raise ValueError("Sell operations are not supported by buy preview")
        if op.status == "in_progress":
            raise ValueError("Order already submitted and is in progress")
        if op.status == "blocked":
            raise ValueError(op.block_reason or "Operation is blocked")

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
            broker_pos = snapshot.bond_positions.get(op.figi)
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
            instrument_uid = _position_instrument_uid(snapshot, op.figi)
            broker_preview = preview_order_price(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=op.figi,
                instrument_uid=instrument_uid,
                direction="BUY",
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        token = self._token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        snapshot = get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
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
            snapshot,
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

        direction = "SELL" if op.kind == "manual_sell" else "BUY"

        order_lots = lots if lots is not None else op.lots
        order_price = price_pct if price_pct is not None else op.suggested_price_pct
        if order_lots is None or order_lots <= 0:
            raise ValueError("Invalid lots")
        if order_price is None:
            raise ValueError("Price is required")

        instrument_uid = _position_instrument_uid(snapshot, op.figi)
        try:
            trade = ensure_order_instrument(
                token,
                figi=op.figi,
                instrument_uid=instrument_uid,
                isin=op.isin,
                direction=direction,  # type: ignore[arg-type]
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
            direction=direction,  # type: ignore[arg-type]
            lots=order_lots,
            pending_op_id=op.id,
        )

        try:
            result = post_limit_order(
                token,
                portfolio.account_kind,  # type: ignore[arg-type]
                account_id=account_id,
                figi=op.figi,
                instrument_uid=trade.instrument_uid,
                direction=direction,  # type: ignore[arg-type]
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
                direction=direction,  # type: ignore[arg-type]
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
        await self._repo.save(portfolio)
        return await self.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            reuse_plan=plan,
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        token = self._token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]

        active: TradeRecord | None = None
        for tr in portfolio.trade_records:
            if tr.pending_op_id == op_id and tr.is_active and tr.order_id:
                active = tr
                break
        if active is None:
            raise ValueError("No active order found for this operation")

        cancel_order(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            account_id=account_id,
            order_id=active.order_id,  # type: ignore[arg-type]
        )
        active.status = "EXECUTION_REPORT_STATUS_CANCELLED"
        active.last_state_checked_at = datetime.now(UTC).isoformat(timespec="seconds")
        await self._repo.save(portfolio)
        return await self.sync_portfolio(
            portfolio_id,
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        found = False
        for pos in portfolio.positions:
            if pos.isin == isin:
                pos.put_offer_decision = decision
                found = True
                break
        if not found:
            raise ValueError(f"Position {isin} not found")
        portfolio.touch()
        await self._repo.save(portfolio)
        return await self.sync_portfolio(
            portfolio_id,
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        cancel_top_up_batch(portfolio, batch_id)
        portfolio.touch()
        await self._repo.save(portfolio)
        return await self.sync_portfolio(
            portfolio_id,
            universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
            today=today,
            skip_auto_top_up=True,
        )

    async def get_performance(self, portfolio_id: str) -> dict | None:
        portfolio = await self._repo.get_by_id(portfolio_id)
        if portfolio is None or not portfolio.account_id or not portfolio.account_kind:
            return None
        token = self._token(portfolio.account_kind)
        today = date.today()
        operations = get_account_operations(
            token,
            portfolio.account_kind,
            portfolio.account_id,
            from_date=_operations_from_date(portfolio, today=today),
        )
        snapshot = get_account_snapshot(token, portfolio.account_kind, portfolio.account_id)
        perf = summarize_actual_performance(portfolio, snapshot, operations)
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
        portfolio = await self._get_trading_portfolio(portfolio_id)
        token = self._token(portfolio.account_kind)  # type: ignore[arg-type]
        today = date.today()
        operations = get_account_operations(
            token,
            portfolio.account_kind,  # type: ignore[arg-type]
            portfolio.account_id,  # type: ignore[arg-type]
            from_date=_operations_from_date(portfolio, today=today),
        )
        return sorted(operations, key=lambda op: op.date, reverse=True)
