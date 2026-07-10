"""API tests for in-app notifications."""

from __future__ import annotations

import asyncio
import uuid

from conftest import portfolio_client

from bond_monitor.infrastructure.notifications.notifications_repository import NotificationsRepository
from bond_monitor.infrastructure.persistence.database import get_session_factory


def test_list_notifications_for_portfolio() -> None:
    fingerprint = f"fp-test-{uuid.uuid4().hex}"
    with portfolio_client("Notify Portfolio") as (test_client, pid):

        async def _seed() -> None:
            session_factory = get_session_factory()
            async with session_factory() as session:
                repo = NotificationsRepository(session)
                await repo.upsert_from_bus(
                    fingerprint=fingerprint,
                    portfolio_id=pid,
                    kind="put_offer_action",
                    payload={
                        "portfolio_id": pid,
                        "kind": "put_offer_action",
                        "isin": "RU000TEST",
                        "name": "Test Bond",
                        "lots": 1,
                        "reason": "Submit put-offer",
                        "urgency": "soon",
                        "detail_key": "2026-07-31",
                    },
                    urgency="soon",
                )

        asyncio.run(_seed())

        resp = test_client.get(f"/api/v1/portfolios/{pid}/notifications")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["kind"] == "put_offer_action"
        assert data["notifications"][0]["is_unread"] is True

        notification_id = data["notifications"][0]["id"]
        read_resp = test_client.post(f"/api/v1/notifications/{notification_id}/read")
        assert read_resp.status_code == 204

        unread_resp = test_client.get(
            f"/api/v1/portfolios/{pid}/notifications",
            params={"unread_only": "true"},
        )
        assert unread_resp.status_code == 200
        assert unread_resp.json()["notifications"] == []
