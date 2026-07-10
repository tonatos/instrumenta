"""Background notifier worker entrypoint."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.notifications.deliver_use_case import DeliverNotificationsUseCase
from bond_monitor.application.notifications.scan_use_case import ScanPortfoliosUseCase
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.infrastructure.notifications.ledger_repository import LedgerRepository
from bond_monitor.infrastructure.notifications.notifications_repository import NotificationsRepository
from bond_monitor.infrastructure.notifications.redis_bus import NotificationBus
from bond_monitor.infrastructure.notifications.telegram_client import TelegramNotifier
from bond_monitor.infrastructure.persistence.database import get_session_factory, init_db
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.interfaces.logging_config import configure_logging
from bond_monitor.notifier.settings import get_notifier_settings, get_shared_settings

logger = logging.getLogger(__name__)


async def _run_scan(
    *,
    trading_ctx: TradingContext,
    bond_service: BondService,
    ledger: LedgerRepository,
    bus: NotificationBus | None,
    telegram: TelegramNotifier,
    session_factory,
) -> int:
    async with session_factory() as session:
        repo = PortfolioRepository(session)
        trading_ctx._repo = repo  # noqa: SLF001
        deliver = DeliverNotificationsUseCase(
            ledger=ledger,
            bus=bus,
            telegram=telegram,
            notifications_repo=NotificationsRepository(session),
        )
        scanner = ScanPortfoliosUseCase(
            trading_ctx=trading_ctx,
            bond_service=bond_service,
            deliver=deliver,
        )
        return await scanner.run(today=date.today())


async def _async_main() -> None:
    settings = get_notifier_settings()
    shared = get_shared_settings()
    configure_logging(shared.log_level)
    await init_db()

    session_factory = get_session_factory()
    trading_ctx = TradingContext(
        PortfolioRepository(session_factory()),
        sandbox_token=shared.t_trading_token_sandbox,
        production_token=shared.t_trading_token_production,
    )
    bond_service = BondService(
        key_rate=shared.key_rate,
        tax_rate=shared.tax_rate,
        tinkoff_token=shared.tinkoff_token,
        max_days=shared.max_days,
        min_volume_rub=shared.min_volume_rub,
    )
    ledger = LedgerRepository(settings.notifier_ledger_path)
    bus: NotificationBus | None = None
    try:
        bus = NotificationBus(settings.redis_url)
        bus.ping()
        logger.info("Connected to Redis at %s", settings.redis_url)
    except Exception:
        logger.warning("Redis unavailable, falling back to direct DB writes", exc_info=True)

    telegram = TelegramNotifier(settings.telegram_bot_token, settings.telegram_notify_user_id)
    interval = max(settings.notifier_scan_interval_sec, 60)
    logger.info("Notifier started, scan interval=%ss", interval)

    while True:
        try:
            count = await _run_scan(
                trading_ctx=trading_ctx,
                bond_service=bond_service,
                ledger=ledger,
                bus=bus,
                telegram=telegram,
                session_factory=session_factory,
            )
            logger.info("Scan complete, alerts processed=%s", count)
        except Exception:
            logger.exception("Notifier scan cycle failed")
        await asyncio.sleep(interval)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
