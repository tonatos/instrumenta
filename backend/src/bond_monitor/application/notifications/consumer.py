"""Background Redis consumer for in-app notifications."""

from __future__ import annotations

import asyncio
import logging

from bond_monitor.infrastructure.notifications.notifications_repository import NotificationsRepository
from bond_monitor.infrastructure.notifications.redis_bus import NotificationBus
from bond_monitor.infrastructure.persistence.database import get_session_factory

logger = logging.getLogger(__name__)


class NotificationConsumer:
    def __init__(self, redis_url: str, *, consumer_name: str = "api-1") -> None:
        self._bus = NotificationBus(redis_url)
        self._consumer_name = consumer_name
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        try:
            self._bus.ensure_consumer_group()
        except Exception:
            logger.warning("Redis consumer group setup failed", exc_info=True)
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("Notification consumer started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _loop(self) -> None:
        session_factory = get_session_factory()
        while not self._stop.is_set():
            try:
                messages = await asyncio.to_thread(
                    self._bus.read_group,
                    self._consumer_name,
                    count=20,
                )
                if not messages:
                    continue
                async with session_factory() as session:
                    repo = NotificationsRepository(session)
                    for message in messages:
                        await repo.upsert_from_bus(
                            fingerprint=message.fingerprint,
                            portfolio_id=message.portfolio_id,
                            kind=message.kind,
                            payload=message.payload,
                            urgency=message.urgency,
                        )
                        await asyncio.to_thread(self._bus.ack, message.message_id)
            except Exception:
                logger.exception("Notification consumer iteration failed")
                await asyncio.sleep(2)
