"""Notifier worker settings — notifier-specific env only."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bond_monitor.interfaces.config import get_settings

_REPO_ROOT = Path(__file__).resolve().parents[4]


class NotifierSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://localhost:6379/0"
    notifier_scan_interval_sec: int = 3600
    telegram_bot_token: str = ""
    telegram_notify_user_id: int = 0
    notifier_ledger_path: Path = _REPO_ROOT / "cache" / "notifier_ledger.db"

    @field_validator("telegram_notify_user_id", mode="before")
    @classmethod
    def _parse_telegram_notify_user_id(cls, value: object) -> int:
        if value is None or value == "":
            return 0
        return int(value)


@lru_cache
def get_notifier_settings() -> NotifierSettings:
    return NotifierSettings()


def get_shared_settings():
    return get_settings()
