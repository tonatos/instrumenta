"""Unit tests for Telegram OIDC helpers."""

from __future__ import annotations

import base64
import hashlib
import time
from unittest.mock import AsyncMock, patch

import pytest

from bond_monitor.interfaces.auth.telegram_oidc import (
    TelegramOidcError,
    TelegramOidcForbidden,
    build_authorization_url,
    create_oauth_state,
    exchange_authorization_code,
    generate_pkce_pair,
    parse_oauth_state,
    verify_id_token,
)

AUTH_SECRET = "test-auth-secret-at-least-32-bytes-long"
CLIENT_ID = "123456789"


def test_generate_pkce_pair() -> None:
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_oauth_state_roundtrip() -> None:
    verifier, _ = generate_pkce_pair()
    nonce = "nonce-123"
    state = create_oauth_state(code_verifier=verifier, nonce=nonce, secret=AUTH_SECRET)
    parsed = parse_oauth_state(state, secret=AUTH_SECRET)
    assert parsed.code_verifier == verifier
    assert parsed.nonce == nonce


def test_oauth_state_rejects_tampered_token() -> None:
    state = create_oauth_state(code_verifier="verifier", nonce="nonce", secret=AUTH_SECRET)
    with pytest.raises(TelegramOidcError, match="state"):
        parse_oauth_state(state + "x", secret=AUTH_SECRET)


def test_build_authorization_url_contains_required_params() -> None:
    verifier, challenge = generate_pkce_pair()
    state = create_oauth_state(code_verifier=verifier, nonce="nonce", secret=AUTH_SECRET)
    url = build_authorization_url(
        client_id=CLIENT_ID,
        redirect_uri="http://localhost:5173/login/callback",
        code_challenge=challenge,
        state=state,
        nonce="nonce",
    )
    assert "https://oauth.telegram.org/auth?" in url
    assert "client_id=123456789" in url
    assert "redirect_uri=" in url
    assert "code_challenge=" in url
    assert "scope=openid+profile" in url or "scope=openid%20profile" in url


def test_verify_id_token_rejects_bad_nonce() -> None:
    with patch("bond_monitor.interfaces.auth.telegram_oidc._decode_id_token") as decode_mock:
        decode_mock.return_value = {
            "iss": "https://oauth.telegram.org",
            "aud": CLIENT_ID,
            "id": 42,
            "exp": int(time.time()) + 3600,
            "nonce": "other",
        }
        with pytest.raises(TelegramOidcError, match="nonce"):
            verify_id_token("mock.id.token", client_id=CLIENT_ID, expected_nonce="expected")


@pytest.mark.asyncio
async def test_exchange_authorization_code_reports_token_error() -> None:
    with patch(
        "bond_monitor.interfaces.auth.telegram_oidc.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=type(
            "Resp",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"error": "invalid_grant", "error_description": "code expired"},
            },
        )(),
    ):
        with pytest.raises(TelegramOidcError, match="invalid_grant"):
            await exchange_authorization_code(
                code="auth-code",
                code_verifier="verifier",
                nonce="nonce",
                client_id=CLIENT_ID,
                client_secret="secret",
                redirect_uri="http://localhost:5173/login/callback",
                allowed_ids=[42],
            )


@pytest.mark.asyncio
async def test_exchange_authorization_code_whitelist() -> None:
    id_token = "mock.id.token"
    token_response = {"id_token": id_token, "access_token": "at", "token_type": "Bearer", "expires_in": 3600}
    claims = {
        "iss": "https://oauth.telegram.org",
        "aud": CLIENT_ID,
        "id": 42,
        "name": "Test User",
        "exp": int(time.time()) + 3600,
        "nonce": "nonce",
    }
    with (
        patch(
            "bond_monitor.interfaces.auth.telegram_oidc.httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=type("Resp", (), {"raise_for_status": lambda self: None, "json": lambda self: token_response})(),
        ),
        patch("bond_monitor.interfaces.auth.telegram_oidc.verify_id_token", return_value=claims),
    ):
        user = await exchange_authorization_code(
            code="auth-code",
            code_verifier="verifier",
            nonce="nonce",
            client_id=CLIENT_ID,
            client_secret="secret",
            redirect_uri="http://localhost:5173/login/callback",
            allowed_ids=[42],
        )
    assert user.telegram_id == 42
    assert user.display_name == "Test User"


@pytest.mark.asyncio
async def test_exchange_authorization_code_forbidden() -> None:
    id_token = "mock.id.token"
    token_response = {"id_token": id_token}
    claims = {"id": 99, "name": "Other", "nonce": "nonce"}
    with (
        patch(
            "bond_monitor.interfaces.auth.telegram_oidc.httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=type("Resp", (), {"raise_for_status": lambda self: None, "json": lambda self: token_response})(),
        ),
        patch("bond_monitor.interfaces.auth.telegram_oidc.verify_id_token", return_value=claims),
    ):
        with pytest.raises(TelegramOidcForbidden, match="not allowed"):
            await exchange_authorization_code(
                code="auth-code",
                code_verifier="verifier",
                nonce="nonce",
                client_id=CLIENT_ID,
                client_secret="secret",
                redirect_uri="http://localhost:5173/login/callback",
                allowed_ids=[42],
            )
