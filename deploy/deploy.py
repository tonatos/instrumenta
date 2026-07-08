"""Deploy Bond Monitor to a VPS via Docker Compose."""

from __future__ import annotations

from pyinfra import host
from pyinfra.operations import apt, docker, files, server

APP_DIR = host.data.app_dir
PROJECT_NAME = host.data.get("project_name", "bond-monitor")
COMPOSE_FILES = host.data.get(
    "compose_files",
    ["docker-compose.yml", "docker-compose.prod.yml"],
)

apt.packages(
    name="Install prerequisites",
    packages=["ca-certificates", "curl"],
    _sudo=True,
)

server.shell(
    name="Install Docker",
    commands=[
        "command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh",
        "docker compose version >/dev/null 2>&1 || apt-get update && apt-get install -y docker-compose-plugin",
    ],
    _sudo=True,
)

files.directory(
    name="Ensure app directory exists",
    path=APP_DIR,
    mode="755",
    _sudo=True,
)

files.sync(
    name="Sync application sources",
    src="..",
    dest=APP_DIR,
    delete=True,
    exclude=[
        ".env",
        ".env.*",
        ".git",
        ".gitignore",
        ".cursor",
        ".venv",
        "venv",
        "__pycache__",
        "*.pyc",
        "cache",
        "node_modules",
        "frontend/node_modules",
        "frontend/dist",
        "e2e",
        "deploy/inventory.py",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.log",
    ],
    exclude_dir=[
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "e2e",
    ],
    _sudo=True,
)

def _allowed_telegram_ids() -> str:
    value = host.data.get("allowed_telegram_ids", "")
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


files.template(
    name="Generate production .env",
    src="templates/env.prod.j2",
    dest=f"{APP_DIR}/.env",
    mode="600",
    domain=host.data.domain,
    tinkoff_token=host.data.get("tinkoff_token", ""),
    t_trading_token_sandbox=host.data.get("t_trading_token_sandbox", ""),
    t_trading_token_production=host.data.get("t_trading_token_production", ""),
    key_rate=host.data.get("key_rate", 14.5),
    tax_rate=host.data.get("tax_rate", 13),
    max_days=host.data.get("max_days", 120),
    min_volume_rub=host.data.get("min_volume_rub", 500_000),
    log_level=host.data.get("log_level", "INFO"),
    auth_disabled=str(host.data.get("auth_disabled", False)).lower(),
    auth_secret=host.data.get("auth_secret", ""),
    telegram_bot_token=host.data.get("telegram_bot_token", ""),
    telegram_bot_username=host.data.get("telegram_bot_username", ""),
    allowed_telegram_ids=_allowed_telegram_ids(),
    _sudo=True,
)

docker.compose(
    name="Deploy Bond Monitor stack",
    project_directory=APP_DIR,
    project_name=PROJECT_NAME,
    files=COMPOSE_FILES,
    build=True,
    pull="missing",
    _sudo=True,
)
