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
    AuthController,
    BondsController,
    CalculatorController,
    ConfigController,
    FavoritesController,
    HealthController,
    NotificationsController,
    PortfoliosController,
    RatingsController,
    TradingController,
)
from bond_monitor.application.notifications.consumer import NotificationConsumer
from bond_monitor.interfaces.auth.jwt_auth import get_jwt_auth
from bond_monitor.interfaces.config import get_settings
from bond_monitor.infrastructure.bonds.universe_cache import configure_ttl as configure_bond_cache_ttl
from bond_monitor.interfaces.logging_config import configure_logging

logger = logging.getLogger(__name__)


@listener("after_exception")
async def log_unhandled_exception(exc: Exception) -> None:
    logger.exception("Unhandled exception during request", exc_info=exc)


@asynccontextmanager
async def lifespan(app: Litestar):
    await init_db()
    await migrate_json_to_db()
    settings = get_settings()
    consumer = NotificationConsumer(settings.redis_url)
    await consumer.start()
    try:
        yield
    finally:
        await consumer.stop()


def create_app() -> Litestar:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_bond_cache_ttl(settings.bond_cache_ttl_sec)
    on_app_init: list = []
    if settings.auth_enabled:
        on_app_init.append(get_jwt_auth().on_app_init)
    return Litestar(
        route_handlers=[
            HealthController,
            AuthController,
            ConfigController,
            BondsController,
            FavoritesController,
            PortfoliosController,
            CalculatorController,
            RatingsController,
            TradingController,
            NotificationsController,
        ],
        dependencies={
            "db_session": Provide(get_db_session),
            "settings": Provide(get_settings),
        },
        cors_config=CORSConfig(allow_origins=settings.cors_origins, allow_credentials=True),
        lifespan=[lifespan],
        debug=settings.debug,
        listeners=[log_unhandled_exception],
        on_app_init=on_app_init,
    )


app = create_app()
