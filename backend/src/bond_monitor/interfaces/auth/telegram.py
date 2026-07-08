"""Telegram Login Widget signature verification."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from bond_monitor.interfaces.auth.models import TelegramUser


class TelegramAuthError(Exception):
    """Invalid or expired Telegram login payload."""


class TelegramAuthForbidden(Exception):
    """Telegram user is not in the whitelist."""


def verify_telegram_login(
    payload: dict[str, Any],
    *,
    bot_token: str,
    allowed_ids: list[int],
    max_age_seconds: int = 86_400,
) -> TelegramUser:
    """Verify Telegram widget payload and ensure user id is whitelisted."""
    if not bot_token:
        raise TelegramAuthError("Telegram bot token is not configured")

    received_hash = str(payload.get("hash", ""))
    if not received_hash:
        raise TelegramAuthError("Missing Telegram login signature")

    check_items = {k: v for k, v in payload.items() if k != "hash" and v is not None}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(check_items.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthError("Invalid Telegram login signature")

    try:
        auth_date = int(payload["auth_date"])
        telegram_id = int(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramAuthError("Invalid Telegram login payload") from exc

    if int(time.time()) - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram login payload expired")

    if telegram_id not in allowed_ids:
        raise TelegramAuthForbidden("User not allowed")

    first_name = str(payload.get("first_name") or "")
    username = payload.get("username")
    return TelegramUser(
        telegram_id=telegram_id,
        display_name=first_name,
        username=str(username) if username else None,
    )
