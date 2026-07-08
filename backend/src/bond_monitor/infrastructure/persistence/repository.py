"""Portfolio repository — SQLAlchemy implementation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.infrastructure.persistence.orm_models import PortfolioRow


class PortfolioRepository:
    """Async repository for Portfolio aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Portfolio]:
        result = await self._session.execute(select(PortfolioRow).order_by(PortfolioRow.created_at))
        return [self._to_domain(row) for row in result.scalars()]

    async def get_by_id(self, portfolio_id: str) -> Portfolio | None:
        result = await self._session.execute(
            select(PortfolioRow).where(PortfolioRow.id == portfolio_id)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, portfolio: Portfolio) -> Portfolio:
        row = await self._session.get(PortfolioRow, portfolio.id)
        if row is None:
            row = PortfolioRow(id=portfolio.id)
            self._session.add(row)
        self._from_domain(row, portfolio)
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def delete(self, portfolio_id: str) -> bool:
        row = await self._session.get(PortfolioRow, portfolio_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True

    def _to_domain(self, row: PortfolioRow) -> Portfolio:
        data = dict(row.data or {})
        data.update(
            {
                "id": row.id,
                "name": row.name,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "initial_amount_rub": row.initial_amount_rub,
                "horizon_date": row.horizon_date.isoformat(),
                "risk_profile": row.risk_profile,
                "cash_balance_rub": row.cash_balance_rub,
                "mode": row.mode,
                "account_id": row.account_id,
                "account_kind": row.account_kind,
            }
        )
        return Portfolio.from_dict(data)

    def _from_domain(self, row: PortfolioRow, portfolio: Portfolio) -> None:
        d = portfolio.to_dict()
        row.name = portfolio.name
        row.created_at = datetime.fromisoformat(d["created_at"])
        if row.created_at.tzinfo is None:
            row.created_at = row.created_at.replace(tzinfo=UTC)
        row.updated_at = datetime.now(UTC)
        row.initial_amount_rub = portfolio.initial_amount_rub
        row.horizon_date = portfolio.horizon_date
        row.risk_profile = portfolio.risk_profile.value
        row.cash_balance_rub = portfolio.cash_balance_rub
        row.mode = portfolio.mode.value
        row.account_id = portfolio.account_id
        row.account_kind = portfolio.account_kind.value if portfolio.account_kind else None
        # Store nested collections in JSON blob
        row.data = {
            k: v
            for k, v in d.items()
            if k
            not in {
                "id",
                "name",
                "created_at",
                "updated_at",
                "initial_amount_rub",
                "horizon_date",
                "risk_profile",
                "cash_balance_rub",
                "mode",
                "account_id",
                "account_kind",
            }
        }
