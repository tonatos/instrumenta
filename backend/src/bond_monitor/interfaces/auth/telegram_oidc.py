"""Telegram Login via OpenID Connect (Authorization Code + PKCE)."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from bond_monitor.interfaces.auth.models import TelegramUser

AUTH_URL = "https://oauth.telegram.org/auth"
TOKEN_URL = "https://oauth.telegram.org/token"
JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
ISSUER = "https://oauth.telegram.org"
CLOCK_SKEW_SECONDS = 30

_jwks_client: PyJWKClient | None = None


class TelegramOidcError(Exception):
    """Invalid Telegram OIDC response or configuration."""


class TelegramOidcForbidden(Exception):
    """Telegram user is not in the whitelist."""


@dataclass(frozen=True)
class OauthState:
    code_verifier: str
    nonce: str


def generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def create_oauth_state(*, code_verifier: str, nonce: str, secret: str) -> str:
    if not secret:
        raise TelegramOidcError("AUTH_SECRET is not configured")
    return jwt.encode(
        {
            "cv": code_verifier,
            "nonce": nonce,
            "exp": int(time.time()) + int(timedelta(minutes=10).total_seconds()),
        },
        secret,
        algorithm="HS256",
    )


def parse_oauth_state(state: str, *, secret: str) -> OauthState:
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
        return OauthState(
            code_verifier=str(payload["cv"]),
            nonce=str(payload["nonce"]),
        )
    except Exception as exc:
        raise TelegramOidcError("Invalid OAuth state") from exc


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    nonce: str,
    scope: str = "openid profile",
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URL)
    return _jwks_client


def _decode_id_token(id_token: str, *, client_id: str) -> dict[str, Any]:
    signing_key = _get_jwks_client().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        issuer=ISSUER,
        leeway=CLOCK_SKEW_SECONDS,
        options={"verify_aud": False, "require": ["exp", "iss"]},
    )
    audience = claims.get("aud")
    if isinstance(audience, list):
        audiences = {str(item) for item in audience}
    else:
        audiences = {str(audience)} if audience is not None else set()
    if str(client_id) not in audiences:
        raise TelegramOidcError("Invalid JWT audience")
    return claims


def verify_id_token(id_token: str, *, client_id: str, expected_nonce: str) -> dict[str, Any]:
    try:
        claims = _decode_id_token(id_token, client_id=client_id)
    except jwt.PyJWTError as exc:
        raise TelegramOidcError(f"Invalid id_token: {exc}") from exc
    token_nonce = claims.get("nonce")
    if token_nonce is not None and str(token_nonce) != expected_nonce:
        raise TelegramOidcError("JWT nonce mismatch")
    return claims


def _telegram_id_from_claims(claims: dict[str, Any]) -> int:
    raw_id = claims.get("id")
    if raw_id is not None:
        return int(raw_id)
    sub = claims.get("sub")
    if sub is not None and str(sub).isdigit():
        return int(sub)
    raise TelegramOidcError("Telegram id_token is missing user id")


def _user_from_claims(claims: dict[str, Any], *, allowed_ids: list[int]) -> TelegramUser:
    user_id = _telegram_id_from_claims(claims)
    if user_id not in allowed_ids:
        raise TelegramOidcForbidden("User not allowed")
    display_name = str(claims.get("name") or claims.get("given_name") or claims.get("preferred_username") or "")
    username = claims.get("preferred_username")
    return TelegramUser(
        telegram_id=user_id,
        display_name=display_name,
        username=str(username) if username else None,
    )


async def exchange_authorization_code(
    *,
    code: str,
    code_verifier: str,
    nonce: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    allowed_ids: list[int],
) -> TelegramUser:
    if not client_id or not client_secret:
        raise TelegramOidcError("Telegram OIDC client is not configured")
    if not redirect_uri:
        raise TelegramOidcError("Telegram OIDC redirect URI is not configured")

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response.raise_for_status()
        token_data = response.json()

    if token_data.get("error"):
        error = str(token_data.get("error"))
        description = token_data.get("error_description")
        message = f"Telegram token error: {error}"
        if description:
            message = f"{message} ({description})"
        raise TelegramOidcError(message)

    id_token = token_data.get("id_token")
    if not id_token:
        raise TelegramOidcError("Telegram token endpoint returned no id_token")

    claims = verify_id_token(id_token, client_id=client_id, expected_nonce=nonce)
    return _user_from_claims(claims, allowed_ids=allowed_ids)
