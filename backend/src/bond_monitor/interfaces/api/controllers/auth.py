"""Authentication API controller."""

from __future__ import annotations

from typing import Any

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.status_codes import HTTP_201_CREATED

from bond_monitor.interfaces.auth.jwt_auth import create_access_token
from bond_monitor.interfaces.auth.models import AuthUser
from bond_monitor.interfaces.auth.telegram import (
    TelegramAuthError,
    TelegramAuthForbidden,
    verify_telegram_login,
)
from bond_monitor.interfaces.config import Settings
from bond_monitor.interfaces.schemas.api import (
    AuthMeResponse,
    AuthTokenResponse,
    TelegramAuthRequest,
)


class AuthController(Controller):
    path = "/api/v1/auth"

    @post("/telegram", status_code=HTTP_201_CREATED)
    async def telegram_login(
        self,
        data: TelegramAuthRequest,
        settings: Settings,
    ) -> AuthTokenResponse:
        payload = data.model_dump(exclude_none=True)
        try:
            user = verify_telegram_login(
                payload,
                bot_token=settings.telegram_bot_token,
                allowed_ids=settings.allowed_telegram_ids,
            )
        except TelegramAuthError as exc:
            raise NotAuthorizedException(detail=str(exc)) from exc
        except TelegramAuthForbidden as exc:
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
