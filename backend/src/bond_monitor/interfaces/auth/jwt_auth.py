"""JWT authentication setup for Litestar."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Any

from litestar.connection import ASGIConnection
from litestar.security.jwt import JWTAuth, Token

from bond_monitor.interfaces.auth.models import AuthUser
from bond_monitor.interfaces.config import Settings, get_settings


async def retrieve_user_handler(token: Token, _connection: ASGIConnection[Any, Any, Any, Any]) -> AuthUser | None:
    try:
        telegram_id = int(token.sub)
    except (TypeError, ValueError):
        return None
    display_name = ""
    if token.extras:
        display_name = str(token.extras.get("display_name", ""))
    return AuthUser(telegram_id=telegram_id, display_name=display_name)


@lru_cache
def get_jwt_auth() -> JWTAuth[AuthUser]:
    settings = get_settings()
    secret = settings.auth_secret or "insecure-dev-secret-change-me"
    return JWTAuth[AuthUser](
        retrieve_user_handler=retrieve_user_handler,
        token_secret=secret,
        default_token_expiration=timedelta(days=30),
        exclude=["/health", "/api/v1/auth/telegram", "/api/v1/config", "/api/v1/config/"],
    )


def reset_jwt_auth_cache() -> None:
    get_jwt_auth.cache_clear()


def create_access_token(user: AuthUser, settings: Settings | None = None) -> str:
    """Issue JWT for an authenticated Telegram user."""
    _ = settings or get_settings()
    jwt_auth = get_jwt_auth()
    return jwt_auth.create_token(
        identifier=str(user.telegram_id),
        token_extras={"display_name": user.display_name},
    )
