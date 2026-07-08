"""API tests for JWT authentication."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from litestar.testing import TestClient

from bond_monitor.interfaces.auth.jwt_auth import create_access_token, reset_jwt_auth_cache
from bond_monitor.interfaces.auth.models import AuthUser
from bond_monitor.interfaces.config import get_settings
from bond_monitor.main import create_app

BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
AUTH_SECRET = "test-auth-secret"


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


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "42")
    get_settings.cache_clear()
    reset_jwt_auth_cache()
    with TestClient(app=create_app()) as client:
        yield client
    get_settings.cache_clear()
    reset_jwt_auth_cache()


def test_portfolios_requires_auth(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/portfolios/")
    assert response.status_code == 401


def test_portfolios_with_valid_jwt(auth_client: TestClient) -> None:
    token = create_access_token(AuthUser(telegram_id=42, display_name="Test"))
    response = auth_client.get(
        "/api/v1/portfolios/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_telegram_login_returns_token(auth_client: TestClient) -> None:
    payload = _sign_payload(
        {
            "id": 42,
            "first_name": "Test",
            "username": "tester",
            "auth_date": int(time.time()),
        }
    )
    response = auth_client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_telegram_login_forbidden_for_non_whitelisted(auth_client: TestClient) -> None:
    payload = _sign_payload(
        {
            "id": 99,
            "first_name": "Other",
            "auth_date": int(time.time()),
        }
    )
    response = auth_client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 403
