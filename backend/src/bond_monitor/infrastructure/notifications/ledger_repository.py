"""SQLite outbox ledger for notifier delivery guarantees."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bond_monitor.domain.notifications.models import Alert


@dataclass(frozen=True)
class LedgerEntry:
    fingerprint: str
    alert_kind: str
    payload_json: str
    bus_published_at: datetime | None
    telegram_sent_at: datetime | None
    last_attempt_at: datetime | None
    retry_count: int


class LedgerRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_ledger (
                    fingerprint TEXT PRIMARY KEY,
                    alert_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    bus_published_at TEXT,
                    telegram_sent_at TEXT,
                    last_attempt_at TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )

    def ensure_detected(self, fingerprint: str, alert: Alert) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO delivery_ledger
                (fingerprint, alert_kind, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (fingerprint, alert.kind.value, json.dumps(alert.to_payload()), now),
            )
            conn.commit()
            return cursor.rowcount == 1

    def get(self, fingerprint: str) -> LedgerEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM delivery_ledger WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM delivery_ledger").fetchone()
        return int(row["c"]) if row else 0

    def delete_all(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM delivery_ledger")
            conn.commit()
            return cursor.rowcount

    def delete_for_portfolio(self, portfolio_id: str) -> int:
        with self._connect() as conn:
            rows = conn.execute("SELECT fingerprint, payload_json FROM delivery_ledger").fetchall()
            to_delete = [
                row["fingerprint"]
                for row in rows
                if _payload_portfolio_id(row["payload_json"]) == portfolio_id
            ]
            if not to_delete:
                return 0
            placeholders = ",".join("?" for _ in to_delete)
            cursor = conn.execute(
                f"DELETE FROM delivery_ledger WHERE fingerprint IN ({placeholders})",
                to_delete,
            )
            conn.commit()
            return cursor.rowcount

    def mark_bus_published(self, fingerprint: str, *, at: datetime) -> bool:
        return self._mark_timestamp(fingerprint, "bus_published_at", at)

    def mark_telegram_sent(self, fingerprint: str, *, at: datetime) -> bool:
        ts = at.isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE delivery_ledger
                SET telegram_sent_at = ?, last_attempt_at = ?, retry_count = retry_count + 1
                WHERE fingerprint = ?
                """,
                (ts, ts, fingerprint),
            )
            conn.commit()
            return cursor.rowcount == 1

    def _mark_timestamp(self, fingerprint: str, column: str, at: datetime) -> bool:
        ts = at.isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE delivery_ledger
                SET {column} = ?, last_attempt_at = ?, retry_count = retry_count + 1
                WHERE fingerprint = ? AND {column} IS NULL
                """,
                (ts, ts, fingerprint),
            )
            conn.commit()
            return cursor.rowcount == 1

    def list_pending_bus(self) -> list[LedgerEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM delivery_ledger WHERE bus_published_at IS NULL ORDER BY created_at"
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def list_pending_telegram(self) -> list[LedgerEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM delivery_ledger
                WHERE telegram_sent_at IS NULL
                ORDER BY created_at
                """
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> LedgerEntry:
        return LedgerEntry(
            fingerprint=row["fingerprint"],
            alert_kind=row["alert_kind"],
            payload_json=row["payload_json"],
            bus_published_at=_parse_dt(row["bus_published_at"]),
            telegram_sent_at=_parse_dt(row["telegram_sent_at"]),
            last_attempt_at=_parse_dt(row["last_attempt_at"]),
            retry_count=int(row["retry_count"]),
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _payload_portfolio_id(payload_json: str) -> str | None:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return None
    portfolio_id = payload.get("portfolio_id")
    return str(portfolio_id) if portfolio_id else None
