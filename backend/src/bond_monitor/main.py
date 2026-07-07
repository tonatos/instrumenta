"""Litestar application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from litestar import Litestar
from litestar.config.cors import CORSConfig
from litestar.di import Provide
from litestar.events import listener

from bond_monitor.infrastructure.persistence.database import get_db_session, init_db
from bond_monitor.infrastructure.persistence.json_migration import migrate_json_to_db
from bond_monitor.interfaces.api.controllers import (
    BondsController,
    CalculatorController,
    ConfigController,
    FavoritesController,
    HealthController,
    PortfoliosController,
    RatingsController,
    TradingController,
)
from bond_monitor.interfaces.config import get_settings
from bond_monitor.interfaces.logging_config import configure_logging

logger = logging.getLogger(__name__)


@listener("after_exception")
async def log_unhandled_exception(exc: Exception) -> None:
    logger.exception("Unhandled exception during request", exc_info=exc)


@asynccontextmanager
async def lifespan(app: Litestar):
    await init_db()
    await migrate_json_to_db()
    yield


def create_app() -> Litestar:
    settings = get_settings()
    configure_logging(settings.log_level)
    return Litestar(
        route_handlers=[
            HealthController,
            ConfigController,
            BondsController,
            FavoritesController,
            PortfoliosController,
            CalculatorController,
            RatingsController,
            TradingController,
        ],
        dependencies={
            "db_session": Provide(get_db_session),
            "settings": Provide(get_settings),
        },
        cors_config=CORSConfig(allow_origins=settings.cors_origins, allow_credentials=True),
        lifespan=[lifespan],
        debug=settings.debug,
        listeners=[log_unhandled_exception],
    )


app = create_app()
