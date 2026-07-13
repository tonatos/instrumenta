"""Repository tests for deploy sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bond_monitor.domain.trading.deploy_session import DeploySession, DeploySessionItem
from bond_monitor.infrastructure.persistence.database import get_session_factory, init_db
from bond_monitor.infrastructure.persistence.deploy_session_repository import DeploySessionRepository


@pytest.mark.asyncio
async def test_deploy_session_repository_roundtrip() -> None:
    await init_db()
    factory = get_session_factory()
    now = datetime.now(UTC)
    session = DeploySession(
        id="repo-sess-1",
        portfolio_id="portfolio-repo",
        status="active",
        items=[
            DeploySessionItem(
                id="item-1",
                kind="buy",
                isin="RU000A001",
                name="Bond",
                lots=2,
                figi="FIGI-1",
                suggested_price_pct=100.5,
                estimated_amount_rub=20_000.0,
                reason="test",
            )
        ],
        cash_snapshot_rub=80_000.0,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )

    async with factory() as db:
        repo = DeploySessionRepository(db)
        saved = await repo.save(session)
        loaded = await repo.get_active("portfolio-repo")
        assert loaded is not None
        assert loaded.id == saved.id
        assert loaded.items[0].lots == 2

        updated = DeploySession(
            id=saved.id,
            portfolio_id=saved.portfolio_id,
            status="active",
            items=[
                DeploySessionItem(
                    **{
                        **saved.items[0].__dict__,
                        "status": "placed",
                        "order_id": "ord-1",
                    }
                )
            ],
            cash_snapshot_rub=saved.cash_snapshot_rub,
            created_at=saved.created_at,
            expires_at=saved.expires_at,
        )
        await repo.save(updated)
        reloaded = await repo.get_active("portfolio-repo")
        assert reloaded is not None
        assert reloaded.items[0].status == "placed"
