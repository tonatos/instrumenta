"""Redis Stream bus for notification events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis

STREAM_KEY = "bond-monitor:notifications"
CONSUMER_GROUP = "api"


@dataclass(frozen=True)
class BusMessage:
    message_id: str
    fingerprint: str
    portfolio_id: str
    kind: str
    payload: dict[str, Any]
    urgency: str
    created_at: str


class NotificationBus:
    def __init__(self, redis_url: str) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def ensure_consumer_group(self) -> None:
        try:
            self._client.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(
        self,
        *,
        fingerprint: str,
        portfolio_id: str,
        kind: str,
        payload: dict[str, Any],
        urgency: str,
    ) -> str:
        created_at = datetime.now(UTC).isoformat()
        fields = {
            "fingerprint": fingerprint,
            "portfolio_id": portfolio_id,
            "kind": kind,
            "payload": json.dumps(payload, ensure_ascii=False),
            "urgency": urgency,
            "created_at": created_at,
        }
        message_id = self._client.xadd(STREAM_KEY, fields)
        return str(message_id)

    def read_group(self, consumer_name: str, *, count: int = 50) -> list[BusMessage]:
        entries = self._client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=consumer_name,
            streams={STREAM_KEY: ">"},
            count=count,
            block=1000,
        )
        messages: list[BusMessage] = []
        for _stream, items in entries or []:
            for message_id, fields in items:
                messages.append(
                    BusMessage(
                        message_id=message_id,
                        fingerprint=fields["fingerprint"],
                        portfolio_id=fields["portfolio_id"],
                        kind=fields["kind"],
                        payload=json.loads(fields["payload"]),
                        urgency=fields["urgency"],
                        created_at=fields["created_at"],
                    )
                )
        return messages

    def ack(self, message_id: str) -> None:
        self._client.xack(STREAM_KEY, CONSUMER_GROUP, message_id)

    def ping(self) -> bool:
        return bool(self._client.ping())
