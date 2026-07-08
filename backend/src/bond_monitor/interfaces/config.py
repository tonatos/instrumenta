"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime configuration for the Bond Monitor API."""

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "DEBUG"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])

    # Database
    database_url: str = f"sqlite+aiosqlite:///{_REPO_ROOT / 'cache' / 'bond_monitor.db'}"

    # Paths
    cache_dir: Path = _REPO_ROOT / "cache"
    ratings_json_path: Path = _REPO_ROOT / "data" / "ratings.json"

    # Auth (Telegram OIDC + JWT whitelist)
    auth_disabled: bool = False
    auth_secret: str = ""
    public_app_url: str = "http://localhost:5173"
    telegram_oidc_client_id: str = ""
    telegram_oidc_client_secret: str = ""
    telegram_oidc_redirect_uri: str = ""
    allowed_telegram_ids: list[int] = Field(default_factory=list)

    @field_validator(
        "telegram_oidc_client_id",
        "telegram_oidc_client_secret",
        "telegram_oidc_redirect_uri",
        "public_app_url",
        mode="before",
    )
    @classmethod
    def _strip_auth_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    # T-Invest tokens
    tinkoff_token: str = ""
    t_trading_token_sandbox: str = ""
    t_trading_token_production: str = ""

    # Scoring defaults
    key_rate: float = 14.5
    tax_rate: float = 13.0
    max_days: int = 120
    min_volume_rub: float = 500_000.0

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def _parse_allowed_telegram_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [int(item) for item in value]
        return [int(value)]

    @property
    def auth_enabled(self) -> bool:
        return not self.auth_disabled

    @property
    def telegram_oidc_redirect_uri_resolved(self) -> str:
        if self.telegram_oidc_redirect_uri:
            return self.telegram_oidc_redirect_uri
        return f"{self.public_app_url.rstrip('/')}/api/v1/auth/telegram/callback"

    @property
    def telegram_oidc_configured(self) -> bool:
        return bool(
            self.telegram_oidc_client_id
            and self.telegram_oidc_client_secret
            and self.telegram_oidc_redirect_uri_resolved
        )

    @property
    def tax_rate_fraction(self) -> float:
        """Tax rate as fraction (settings store percent, e.g. 13 → 0.13)."""
        return self.tax_rate / 100.0



@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
