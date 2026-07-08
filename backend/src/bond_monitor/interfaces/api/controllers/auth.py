"""Authentication API controller."""

from __future__ import annotations

import secrets
from typing import Any

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.status_codes import HTTP_201_CREATED

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
from bond_monitor.interfaces.schemas.api import (
    AuthMeResponse,
    AuthTokenResponse,
    TelegramOidcCallbackRequest,
    TelegramOidcStartResponse,
)


class AuthController(Controller):
    path = "/api/v1/auth"

    @get("/telegram/start")
    async def telegram_start(self, settings: Settings) -> TelegramOidcStartResponse:
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
        return TelegramOidcStartResponse(authorization_url=authorization_url)

    @post("/telegram/callback", status_code=HTTP_201_CREATED)
    async def telegram_callback(
        self,
        data: TelegramOidcCallbackRequest,
        settings: Settings,
    ) -> AuthTokenResponse:
        try:
            oauth_state = parse_oauth_state(data.state, secret=settings.auth_secret)
            user = await exchange_authorization_code(
                code=data.code,
                code_verifier=oauth_state.code_verifier,
                nonce=oauth_state.nonce,
                client_id=settings.telegram_oidc_client_id,
                client_secret=settings.telegram_oidc_client_secret,
                redirect_uri=settings.telegram_oidc_redirect_uri_resolved,
                allowed_ids=settings.allowed_telegram_ids,
            )
        except TelegramOidcError as exc:
            raise NotAuthorizedException(detail=str(exc)) from exc
        except TelegramOidcForbidden as exc:
            raise PermissionDeniedException(detail=str(exc)) from exc

        token = create_access_token(
            AuthUser(telegram_id=user.telegram_id, display_name=user.display_name),
            settings=settings,
        )
        return AuthTokenResponse(access_token=token)

    @get("/me")
    async def me(self, request: Request[AuthUser, Any, Any]) -> AuthMeResponse:
        user = request.user
        return AuthMeResponse(telegram_id=user.telegram_id, display_name=user.display_name)

    @post("/logout")
    async def logout(self) -> dict[str, str]:
        return {"status": "ok"}
