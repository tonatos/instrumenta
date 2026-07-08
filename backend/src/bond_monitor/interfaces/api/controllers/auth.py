"""Authentication API controller."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import quote

from litestar import Controller, Request, get
from litestar.exceptions import NotAuthorizedException
from litestar.response import Redirect

from bond_monitor.interfaces.auth.jwt_auth import create_access_token
from bond_monitor.interfaces.auth.models import AuthUser
from bond_monitor.interfaces.auth.telegram_oidc import (
    TelegramOidcError,
    TelegramOidcForbidden,
    build_authorization_url,
    create_oauth_state,
    exchange_authorization_code,
    generate_pkce_pair,
    parse_oauth_state,
)
from bond_monitor.interfaces.config import Settings
from bond_monitor.interfaces.schemas.api import AuthMeResponse

logger = logging.getLogger(__name__)


class AuthController(Controller):
    path = "/api/v1/auth"

    @get("/telegram/login")
    async def telegram_login(self, settings: Settings) -> Redirect:
        """Start Telegram OIDC: redirect browser to oauth.telegram.org."""
        if not settings.telegram_oidc_configured:
            raise NotAuthorizedException(detail="Telegram OIDC is not configured")

        code_verifier, code_challenge = generate_pkce_pair()
        nonce = secrets.token_hex(16)
        state = create_oauth_state(
            code_verifier=code_verifier,
            nonce=nonce,
            secret=settings.auth_secret,
        )
        authorization_url = build_authorization_url(
            client_id=settings.telegram_oidc_client_id,
            redirect_uri=settings.telegram_oidc_redirect_uri_resolved,
            code_challenge=code_challenge,
            state=state,
            nonce=nonce,
        )
        return Redirect(path=authorization_url)

    @get("/telegram/callback")
    async def telegram_callback(self, request: Request, settings: Settings) -> Redirect:
        """Telegram OIDC callback: exchange code server-side, redirect to SPA with token."""
        frontend_callback = f"{settings.public_app_url.rstrip('/')}/login/callback"
        error = request.query_params.get("error")
        error_description = request.query_params.get("error_description")
        code = request.query_params.get("code")
        oauth_state = request.query_params.get("state")

        if error:
            return Redirect(
                path=_frontend_error_url(
                    frontend_callback,
                    error,
                    error_description or error,
                )
            )
        if not code or not oauth_state:
            return Redirect(
                path=_frontend_error_url(
                    frontend_callback,
                    "missing_code",
                    "Telegram не вернул код авторизации.",
                )
            )

        try:
            parsed_state = parse_oauth_state(oauth_state, secret=settings.auth_secret)
            user = await exchange_authorization_code(
                code=code,
                code_verifier=parsed_state.code_verifier,
                nonce=parsed_state.nonce,
                client_id=settings.telegram_oidc_client_id,
                client_secret=settings.telegram_oidc_client_secret,
                redirect_uri=settings.telegram_oidc_redirect_uri_resolved,
                allowed_ids=settings.allowed_telegram_ids,
            )
            token = create_access_token(
                AuthUser(telegram_id=user.telegram_id, display_name=user.display_name),
                settings=settings,
            )
            return Redirect(path=f"{frontend_callback}?access_token={quote(token)}")
        except TelegramOidcForbidden as exc:
            logger.warning("Telegram OIDC forbidden: %s", exc)
            return Redirect(path=_frontend_error_url(frontend_callback, "forbidden", str(exc)))
        except TelegramOidcError as exc:
            logger.warning("Telegram OIDC failed: %s", exc)
            return Redirect(path=_frontend_error_url(frontend_callback, "auth_failed", str(exc)))

    @get("/me")
    async def me(self, request: Request[AuthUser, Any, Any]) -> AuthMeResponse:
        user = request.user
        return AuthMeResponse(telegram_id=user.telegram_id, display_name=user.display_name)

    @get("/logout")
    async def logout(self, settings: Settings) -> Redirect:
        return Redirect(path=f"{settings.public_app_url.rstrip('/')}/login")


def _frontend_error_url(frontend_callback: str, error: str, description: str) -> str:
    return (
        f"{frontend_callback}?error={quote(error)}"
        f"&error_description={quote(description)}"
    )
