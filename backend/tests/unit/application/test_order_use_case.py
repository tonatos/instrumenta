"""Order use case hooks for deploy session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.deploy_session_use_case import DeploySessionUseCase
from bond_monitor.domain.trading.deploy_session import DeploySession, DeploySessionItem
from bond_monitor.infrastructure.persistence.deploy_session_repository import DeploySessionRepository
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.infrastructure.persistence.database import get_session_factory, init_db
from bond_monitor.domain.portfolio.models import PortfolioMode
from bond_monitor.domain.trading.models import AccountKind
from factories import make_portfolio


def _active_session(portfolio_id: str = "pid-order") -> DeploySession:
    now = datetime.now(UTC)
    return DeploySession(
        id=f"sess-{portfolio_id}",
        portfolio_id=portfolio_id,
        status="active",
        items=[
            DeploySessionItem(
                id="deploy-item-1",
                kind="buy",
                isin="RU000A001",
                name="Bond A",
                lots=5,
                figi="FIGI-A",
                suggested_price_pct=100.5,
                estimated_amount_rub=50_000.0,
                reason="buy",
            ),
            DeploySessionItem(
                id="deploy-item-2",
                kind="buy",
                isin="RU000A002",
                name="Bond B",
                lots=3,
                figi="FIGI-B",
                suggested_price_pct=101.0,
                estimated_amount_rub=30_000.0,
                reason="buy",
            ),
        ],
        cash_snapshot_rub=80_000.0,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )


@pytest.mark.asyncio
async def test_on_order_placed_marks_session_item() -> None:
    await init_db()
    portfolio = make_portfolio()
    portfolio.id = "pid-order"
    portfolio.mode = PortfolioMode.TRADING
    portfolio.account_id = "acc-order"
    portfolio.account_kind = AccountKind.SANDBOX

    factory = get_session_factory()
    async with factory() as db:
        portfolio_repo = PortfolioRepository(db)
        deploy_repo = DeploySessionRepository(db)
        await portfolio_repo.save(portfolio)
        await deploy_repo.save(_active_session(portfolio.id))

        ctx = TradingContext(
            portfolio_repo,
            sandbox_token="token",
            production_token="",
        )
        use_case = DeploySessionUseCase(ctx, deploy_repo)

        updated = await use_case.on_order_placed(
            portfolio.id,
            "deploy-item-1",
            "broker-order-42",
        )

        assert updated is not None
        placed = next(item for item in updated.items if item.id == "deploy-item-1")
        assert placed.status == "placed"
        assert placed.order_id == "broker-order-42"
        pending = next(item for item in updated.items if item.id == "deploy-item-2")
        assert pending.status == "pending"
        assert pending.lots == 3

        reloaded = await deploy_repo.get_active(portfolio.id)
        assert reloaded is not None
        assert reloaded.items[0].status == "placed"


@pytest.mark.asyncio
async def test_on_order_placed_ignores_unknown_suggestion_id() -> None:
    await init_db()
    portfolio = make_portfolio()
    portfolio.id = "pid-order-2"
    portfolio.mode = PortfolioMode.TRADING
    portfolio.account_id = "acc-order-2"
    portfolio.account_kind = AccountKind.SANDBOX

    factory = get_session_factory()
    async with factory() as db:
        portfolio_repo = PortfolioRepository(db)
        deploy_repo = DeploySessionRepository(db)
        await portfolio_repo.save(portfolio)
        await deploy_repo.save(_active_session(portfolio.id))

        ctx = TradingContext(
            portfolio_repo,
            sandbox_token="token",
            production_token="",
        )
        use_case = DeploySessionUseCase(ctx, deploy_repo)

        result = await use_case.on_order_placed(
            portfolio.id,
            "not-a-session-item",
            "broker-order-99",
        )

        assert result is None
        reloaded = await deploy_repo.get_active(portfolio.id)
        assert all(item.status == "pending" for item in reloaded.items)  # type: ignore[union-attr]
