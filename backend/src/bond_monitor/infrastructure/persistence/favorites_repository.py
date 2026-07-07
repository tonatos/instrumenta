"""Favorites repository."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.infrastructure.persistence.orm_models import FavoriteRow


class FavoritesRepository:
    """Async repository for favorite ISINs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_isins(self) -> list[str]:
        result = await self._session.execute(
            select(FavoriteRow.isin).order_by(FavoriteRow.added_at)
        )
        return list(result.scalars())

    async def add(self, isin: str) -> None:
        existing = await self._session.get(FavoriteRow, isin)
        if existing is None:
            self._session.add(FavoriteRow(isin=isin, added_at=datetime.now(UTC)))
            await self._session.commit()

    async def remove(self, isin: str) -> bool:
        result = await self._session.execute(delete(FavoriteRow).where(FavoriteRow.isin == isin))
        await self._session.commit()
        return result.rowcount > 0

    async def sync_visible(self, isins: set[str]) -> list[str]:
        """Keep only ISINs that are still visible; return removed ISINs."""
        current = set(await self.list_isins())
        to_remove = current - isins
        for isin in to_remove:
            await self.remove(isin)
        return sorted(to_remove)
