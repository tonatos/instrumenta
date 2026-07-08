"""API tests for JWT authentication."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from litestar.testing import TestClient

from bond_monitor.interfaces.auth.jwt_auth import create_access_token, reset_jwt_auth_cache
from bond_monitor.interfaces.auth.models import AuthUser, TelegramUser
from bond_monitor.interfaces.config import get_settings
from bond_monitor.main import create_app

AUTH_SECRET = "test-auth-secret-at-least-32-bytes-long"
CLIENT_ID = "123456789"
CLIENT_SECRET = "oidc-client-secret"
REDIRECT_URI = "http://localhost:5173/login/callback"


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv("TELEGRAM_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("TELEGRAM_OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("TELEGRAM_OIDC_REDIRECT_URI", REDIRECT_URI)
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


def test_telegram_start_returns_authorization_url(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/auth/telegram/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authorization_url"].startswith("https://oauth.telegram.org/auth?")
    assert f"client_id={CLIENT_ID}" in body["authorization_url"]
    assert "redirect_uri=" in body["authorization_url"]


def test_telegram_callback_returns_token(auth_client: TestClient) -> None:
    start = auth_client.get("/api/v1/auth/telegram/start")
    state = _extract_query_param(start.json()["authorization_url"], "state")
    with patch(
        "bond_monitor.interfaces.api.controllers.auth.exchange_authorization_code",
        new_callable=AsyncMock,
        return_value=TelegramUser(telegram_id=42, display_name="Test"),
    ):
        response = auth_client.post(
            "/api/v1/auth/telegram/callback",
            json={"code": "auth-code", "state": state},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_telegram_callback_forbidden_for_non_whitelisted(auth_client: TestClient) -> None:
    from bond_monitor.interfaces.auth.telegram_oidc import TelegramOidcForbidden

    start = auth_client.get("/api/v1/auth/telegram/start")
    state = _extract_query_param(start.json()["authorization_url"], "state")
    with patch(
        "bond_monitor.interfaces.api.controllers.auth.exchange_authorization_code",
        new_callable=AsyncMock,
        side_effect=TelegramOidcForbidden("User not allowed"),
    ):
        response = auth_client.post(
            "/api/v1/auth/telegram/callback",
            json={"code": "auth-code", "state": state},
        )
    assert response.status_code == 403


def _extract_query_param(url: str, key: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(url).query)[key][0]
