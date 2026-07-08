"""Auth domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthUser:
    """Authenticated user resolved from JWT."""

    telegram_id: int
    display_name: str


@dataclass(frozen=True)
class TelegramUser:
    """Verified Telegram Login Widget user."""

    telegram_id: int
    display_name: str
    username: str | None = None
