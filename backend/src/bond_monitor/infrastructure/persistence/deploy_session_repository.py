"""Repository for deploy sessions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.domain.trading.deploy_session import DeploySession
from bond_monitor.infrastructure.persistence.orm_models import DeploySessionRow


class DeploySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_domain(self, row: DeploySessionRow) -> DeploySession:
        return DeploySession.from_dict(
            {
                "id": row.id,
                "portfolio_id": row.portfolio_id,
                "status": row.status,
                "items": row.items_json,
                "cash_snapshot_rub": row.cash_snapshot_rub,
                "created_at": row.created_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "warnings": row.warnings_json or [],
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
        )

    def _to_row(self, session: DeploySession) -> DeploySessionRow:
        return DeploySessionRow(
            id=session.id,
            portfolio_id=session.portfolio_id,
            status=session.status,
            cash_snapshot_rub=session.cash_snapshot_rub,
            items_json=[item.to_dict() for item in session.items],
            warnings_json=list(session.warnings),
            created_at=session.created_at,
            expires_at=session.expires_at,
            completed_at=session.completed_at,
        )

    async def _expire_stale(self, portfolio_id: str, *, now: datetime) -> None:
        await self._session.execute(
            update(DeploySessionRow)
            .where(
                DeploySessionRow.portfolio_id == portfolio_id,
                DeploySessionRow.status == "active",
                DeploySessionRow.expires_at <= now,
            )
            .values(status="expired")
        )

    async def get_active(self, portfolio_id: str) -> DeploySession | None:
        now = datetime.now(UTC)
        await self._expire_stale(portfolio_id, now=now)
        result = await self._session.execute(
            select(DeploySessionRow)
            .where(
                DeploySessionRow.portfolio_id == portfolio_id,
                DeploySessionRow.status == "active",
                DeploySessionRow.expires_at > now,
            )
            .order_by(DeploySessionRow.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def get_by_id(self, session_id: str) -> DeploySession | None:
        result = await self._session.execute(
            select(DeploySessionRow).where(DeploySessionRow.id == session_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain(row)

    async def save(self, deploy_session: DeploySession) -> DeploySession:
        result = await self._session.execute(
            select(DeploySessionRow).where(DeploySessionRow.id == deploy_session.id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = self._to_row(deploy_session)
            self._session.add(row)
        else:
            row.status = deploy_session.status
            row.cash_snapshot_rub = deploy_session.cash_snapshot_rub
            row.items_json = [item.to_dict() for item in deploy_session.items]
            row.warnings_json = list(deploy_session.warnings)
            row.expires_at = deploy_session.expires_at
            row.completed_at = deploy_session.completed_at
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def has_active(self, portfolio_id: str) -> bool:
        return await self.get_active(portfolio_id) is not None
