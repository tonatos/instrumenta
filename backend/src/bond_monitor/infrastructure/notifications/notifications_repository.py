"""Async repository for in-app notifications."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.infrastructure.persistence.orm_models import UserNotificationRow
from bond_monitor.domain.trading.ids import stable_id


class NotificationRecord:
    def __init__(self, row: UserNotificationRow) -> None:
        self.id = row.id
        self.fingerprint = row.fingerprint
        self.portfolio_id = row.portfolio_id
        self.kind = row.kind
        self.payload = dict(row.payload_json or {})
        self.urgency = row.urgency
        self.created_at = row.created_at
        self.read_at = row.read_at
        self.dismissed_at = row.dismissed_at

    @property
    def is_unread(self) -> bool:
        return self.read_at is None and self.dismissed_at is None


class NotificationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_from_bus(
        self,
        *,
        fingerprint: str,
        portfolio_id: str,
        kind: str,
        payload: dict[str, Any],
        urgency: str,
        created_at: datetime | None = None,
    ) -> NotificationRecord:
        result = await self._session.execute(
            select(UserNotificationRow).where(UserNotificationRow.fingerprint == fingerprint)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = UserNotificationRow(
                id=stable_id("notification", fingerprint, kind),
                fingerprint=fingerprint,
                portfolio_id=portfolio_id,
                kind=kind,
                payload_json=payload,
                urgency=urgency,
                created_at=created_at or datetime.now(UTC),
            )
            self._session.add(row)
        else:
            row.portfolio_id = portfolio_id
            row.kind = kind
            row.payload_json = payload
            row.urgency = urgency
        await self._session.commit()
        await self._session.refresh(row)
        return NotificationRecord(row)

    async def list_for_portfolio(
        self,
        portfolio_id: str,
        *,
        unread_only: bool = False,
    ) -> list[NotificationRecord]:
        query = (
            select(UserNotificationRow)
            .where(UserNotificationRow.portfolio_id == portfolio_id)
            .order_by(UserNotificationRow.created_at.desc())
        )
        if unread_only:
            query = query.where(
                UserNotificationRow.read_at.is_(None),
                UserNotificationRow.dismissed_at.is_(None),
            )
        result = await self._session.execute(query)
        return [NotificationRecord(row) for row in result.scalars()]

    async def get_by_id(self, notification_id: str) -> NotificationRecord | None:
        row = await self._session.get(UserNotificationRow, notification_id)
        return NotificationRecord(row) if row else None

    async def mark_read(self, notification_id: str) -> NotificationRecord | None:
        row = await self._session.get(UserNotificationRow, notification_id)
        if row is None:
            return None
        row.read_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return NotificationRecord(row)

    async def dismiss(self, notification_id: str) -> NotificationRecord | None:
        row = await self._session.get(UserNotificationRow, notification_id)
        if row is None:
            return None
        row.dismissed_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(row)
        return NotificationRecord(row)
