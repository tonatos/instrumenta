"""Unit tests for Telegram Login Widget signature verification."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from bond_monitor.interfaces.auth.telegram import (
    TelegramAuthError,
    TelegramAuthForbidden,
    verify_telegram_login,
)

BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


def _sign_payload(payload: dict[str, str | int], bot_token: str = BOT_TOKEN) -> dict[str, str | int]:
    data = {k: v for k, v in payload.items() if k != "hash"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    signed = dict(data)
    signed["hash"] = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return signed


def _valid_payload(*, user_id: int = 42, auth_date: int | None = None) -> dict[str, str | int]:
    return _sign_payload(
        {
            "id": user_id,
            "first_name": "Test",
            "username": "tester",
            "auth_date": auth_date if auth_date is not None else int(time.time()),
        }
    )


def test_valid_signature_passes_whitelist() -> None:
    payload = _valid_payload(user_id=42)
    user = verify_telegram_login(
        payload,
        bot_token=BOT_TOKEN,
        allowed_ids=[42],
    )
    assert user.telegram_id == 42
    assert user.display_name == "Test"


def test_invalid_signature_raises() -> None:
    payload = _valid_payload()
    payload["hash"] = "deadbeef"
    with pytest.raises(TelegramAuthError, match="signature"):
        verify_telegram_login(payload, bot_token=BOT_TOKEN, allowed_ids=[42])


def test_expired_auth_date_raises() -> None:
    payload = _valid_payload(auth_date=int(time.time()) - 86_400 - 1)
    with pytest.raises(TelegramAuthError, match="expired"):
        verify_telegram_login(
            payload,
            bot_token=BOT_TOKEN,
            allowed_ids=[42],
            max_age_seconds=86_400,
        )


def test_id_not_in_whitelist_raises_forbidden() -> None:
    payload = _valid_payload(user_id=99)
    with pytest.raises(TelegramAuthForbidden, match="not allowed"):
        verify_telegram_login(payload, bot_token=BOT_TOKEN, allowed_ids=[42])
