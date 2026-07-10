"""In-app notifications API."""

from __future__ import annotations

from litestar import Controller, get, post
from litestar.di import Provide
from litestar.exceptions import NotFoundException
from litestar.status_codes import HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.infrastructure.notifications.notifications_repository import NotificationsRepository
from bond_monitor.interfaces.schemas.api import NotificationResponse, NotificationsListResponse


async def provide_notifications_repo(db_session: AsyncSession) -> NotificationsRepository:
    return NotificationsRepository(db_session)


def _to_response(record) -> NotificationResponse:
    return NotificationResponse(
        id=record.id,
        fingerprint=record.fingerprint,
        portfolio_id=record.portfolio_id,
        kind=record.kind,
        payload=record.payload,
        urgency=record.urgency,
        created_at=record.created_at.isoformat(),
        read_at=record.read_at.isoformat() if record.read_at else None,
        dismissed_at=record.dismissed_at.isoformat() if record.dismissed_at else None,
        is_unread=record.is_unread,
    )


class NotificationsController(Controller):
    path = "/api/v1"
    dependencies = {"notifications_repo": Provide(provide_notifications_repo)}

    @get("/portfolios/{portfolio_id:str}/notifications")
    async def list_notifications(
        self,
        portfolio_id: str,
        notifications_repo: NotificationsRepository,
        unread_only: bool = False,
    ) -> NotificationsListResponse:
        records = await notifications_repo.list_for_portfolio(
            portfolio_id,
            unread_only=unread_only,
        )
        return NotificationsListResponse(
            notifications=[_to_response(record) for record in records]
        )

    @post("/notifications/{notification_id:str}/read", status_code=HTTP_204_NO_CONTENT)
    async def mark_read(
        self,
        notification_id: str,
        notifications_repo: NotificationsRepository,
    ) -> None:
        record = await notifications_repo.mark_read(notification_id)
        if record is None:
            raise NotFoundException(detail="Notification not found")

    @post("/notifications/{notification_id:str}/dismiss", status_code=HTTP_204_NO_CONTENT)
    async def dismiss(
        self,
        notification_id: str,
        notifications_repo: NotificationsRepository,
    ) -> None:
        record = await notifications_repo.dismiss(notification_id)
        if record is None:
            raise NotFoundException(detail="Notification not found")
