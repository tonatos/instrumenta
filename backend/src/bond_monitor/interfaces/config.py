"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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

    # T-Invest tokens
    tinkoff_token: str = ""
    t_trading_token_sandbox: str = ""
    t_trading_token_production: str = ""

    # Scoring defaults
    key_rate: float = 14.5
    tax_rate: float = 13.0
    max_days: int = 120
    min_volume_rub: float = 500_000.0

    @property
    def tax_rate_fraction(self) -> float:
        """Tax rate as fraction (settings store percent, e.g. 13 → 0.13)."""
        return self.tax_rate / 100.0



@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
