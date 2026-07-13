"""Deploy session lifecycle — frozen buy/reinvest plan."""

from __future__ import annotations

from datetime import UTC, date, datetime
from dataclasses import replace
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.trading.advisory import build_holdings, effective_trading_positions
from bond_monitor.domain.trading.deploy_session import (
    DeploySession,
    apply_session_staleness,
    build_deploy_session_plan,
    find_session_item,
    is_session_active,
    mark_item_placed,
    mark_item_skipped,
    session_has_pending_items,
    sync_session_with_orders,
    complete_session_if_no_pending,
)
from bond_monitor.domain.trading.policies import DeploySessionPolicy
from bond_monitor.infrastructure.persistence.deploy_session_repository import DeploySessionRepository
from bond_monitor.infrastructure.tinvest.snapshot_adapter import broker_snapshot_from_infrastructure
from bond_monitor.application.trading import broker


class DeploySessionConflictError(Exception):
    """Active deploy session already exists."""


class DeploySessionNotFoundError(Exception):
    """Deploy session not found."""


class DeploySessionEmptyError(Exception):
    """No buy/reinvest recommendations to freeze."""


class DeploySessionUseCase:
    def __init__(
        self,
        ctx: TradingContext,
        deploy_repo: DeploySessionRepository,
        *,
        policy: DeploySessionPolicy = DeploySessionPolicy(),
    ) -> None:
        self._ctx = ctx
        self._deploy_repo = deploy_repo
        self._policy = policy

    async def get_active(self, portfolio_id: str) -> DeploySession | None:
        return await self._deploy_repo.get_active(portfolio_id)

    async def save_session(self, session: DeploySession) -> DeploySession:
        return await self._deploy_repo.save(session)

    async def create_session(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> DeploySession:
        active = await self._deploy_repo.get_active(portfolio_id)
        if active is not None:
            completed = complete_session_if_no_pending(active)
            if completed.status == "completed":
                await self._deploy_repo.save(completed)
            elif session_has_pending_items(active):
                raise DeploySessionConflictError(
                    "Уже есть активный план закупки — завершите или отмените его"
                )

        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]
        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)

        holdings = build_holdings(broker_snapshot, universe)
        positions = effective_trading_positions(
            portfolio,
            broker_snapshot,
            universe,
            purchase_date=today,
        )
        session = build_deploy_session_plan(
            portfolio,
            holdings,
            positions,
            universe,
            available_cash=float(broker_snapshot.available_money_rub),
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            policy=self._policy,
        )
        if not session.items:
            raise DeploySessionEmptyError("Нет рекомендаций для фиксации плана")

        return await self._deploy_repo.save(session)

    async def refresh_session(
        self,
        portfolio_id: str,
        session_id: str,
        universe: list[BondRecord],
        *,
        key_rate: float,
        tax_rate: float,
        today: date,
    ) -> DeploySession:
        existing = await self._deploy_repo.get_by_id(session_id)
        if existing is None or existing.portfolio_id != portfolio_id:
            raise DeploySessionNotFoundError("Сессия не найдена")
        if existing.status != "active":
            raise DeploySessionNotFoundError("Сессия не активна")

        portfolio = await self._ctx.get_trading_portfolio(portfolio_id)
        token = self._ctx.token(portfolio.account_kind)  # type: ignore[arg-type]
        account_id = portfolio.account_id  # type: ignore[assignment]
        snapshot = broker.get_account_snapshot(token, portfolio.account_kind, account_id)  # type: ignore[arg-type]
        broker_snapshot = broker_snapshot_from_infrastructure(snapshot)

        holdings = build_holdings(broker_snapshot, universe)
        positions = effective_trading_positions(
            portfolio,
            broker_snapshot,
            universe,
            purchase_date=today,
        )
        refreshed = build_deploy_session_plan(
            portfolio,
            holdings,
            positions,
            universe,
            available_cash=float(broker_snapshot.available_money_rub),
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            policy=self._policy,
            session_id=existing.id,
        )
        if not refreshed.items:
            raise DeploySessionEmptyError("Нет рекомендаций для обновления плана")
        refreshed = DeploySession(
            id=existing.id,
            portfolio_id=existing.portfolio_id,
            status="active",
            items=refreshed.items,
            cash_snapshot_rub=refreshed.cash_snapshot_rub,
            created_at=existing.created_at,
            expires_at=refreshed.expires_at,
            warnings=[],
        )
        return await self._deploy_repo.save(refreshed)

    async def cancel_session(self, portfolio_id: str, session_id: str) -> DeploySession:
        session = await self._deploy_repo.get_by_id(session_id)
        if session is None or session.portfolio_id != portfolio_id:
            raise DeploySessionNotFoundError("Сессия не найдена")
        cancelled = replace(
            session,
            status="cancelled",
            completed_at=datetime.now(UTC),
        )
        return await self._deploy_repo.save(cancelled)

    async def skip_item(
        self,
        portfolio_id: str,
        session_id: str,
        item_id: str,
    ) -> DeploySession:
        session = await self._deploy_repo.get_by_id(session_id)
        if session is None or session.portfolio_id != portfolio_id:
            raise DeploySessionNotFoundError("Сессия не найдена")
        if not is_session_active(session):
            raise DeploySessionNotFoundError("Сессия не активна")
        if find_session_item(session, item_id) is None:
            raise DeploySessionNotFoundError("Позиция не найдена в плане")
        updated = mark_item_skipped(session, item_id)
        return await self._deploy_repo.save(updated)

    async def on_order_placed(
        self,
        portfolio_id: str,
        suggestion_id: str | None,
        order_id: str,
    ) -> DeploySession | None:
        if not suggestion_id:
            return None
        session = await self._deploy_repo.get_active(portfolio_id)
        if session is None:
            return None
        if find_session_item(session, suggestion_id) is None:
            return None
        updated = mark_item_placed(session, suggestion_id, order_id)
        return await self._deploy_repo.save(updated)

    async def sync_active_session(
        self,
        portfolio_id: str,
        universe: list[BondRecord],
        *,
        portfolio,
        active_orders,
    ) -> DeploySession | None:
        session = await self._deploy_repo.get_active(portfolio_id)
        if session is None:
            return None

        synced = sync_session_with_orders(session, active_orders)
        return apply_session_staleness(
            synced,
            universe,
            portfolio=portfolio,
            policy=self._policy,
        )
