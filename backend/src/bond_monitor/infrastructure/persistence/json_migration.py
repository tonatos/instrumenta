"""One-time migration from JSON files to SQLAlchemy database."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.infrastructure.paths import get_cache_dir
from bond_monitor.infrastructure.persistence.database import get_session_factory
from bond_monitor.infrastructure.persistence.favorites_repository import FavoritesRepository
from bond_monitor.infrastructure.persistence.orm_models import FavoriteRow, PortfolioRow
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository

logger = logging.getLogger(__name__)


async def migrate_json_to_db() -> None:
    """Import portfolios.json and favorites.json if DB is empty."""
    cache = get_cache_dir()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(PortfolioRow).limit(1))
        if result.scalar_one_or_none() is not None:
            return

        portfolios_path = cache / "portfolios.json"
        if portfolios_path.exists():
            raw = json.loads(portfolios_path.read_text(encoding="utf-8"))
            repo = PortfolioRepository(session)
            for item in raw.get("portfolios", []):
                portfolio = Portfolio.from_dict(item)
                await repo.save(portfolio)
            logger.info("Migrated %d portfolios from JSON", len(raw.get("portfolios", [])))

        favorites_path = cache / "favorites.json"
        if favorites_path.exists():
            raw = json.loads(favorites_path.read_text(encoding="utf-8"))
            fav_repo = FavoritesRepository(session)
            for isin in raw.get("isins", []):
                session.add(
                    FavoriteRow(isin=isin, added_at=datetime.now(UTC))
                )
            await session.commit()
            logger.info("Migrated %d favorites from JSON", len(raw.get("isins", [])))
