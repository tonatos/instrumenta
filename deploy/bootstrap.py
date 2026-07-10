"""First-time VPS bootstrap: Docker, git clone, .env, compose up."""

from __future__ import annotations

from pyinfra import host
from pyinfra.operations import apt, docker, files, git, server

APP_DIR = host.data.app_dir
PROJECT_NAME = host.data.get("project_name", "bond-monitor")
COMPOSE_FILE_NAMES = host.data.get(
    "compose_files",
    ["docker-compose.yml", "docker-compose.prod.yml"],
)
COMPOSE_FILES = [f"{APP_DIR}/{name}" for name in COMPOSE_FILE_NAMES]
GIT_REPO = host.data.git_repo
GIT_BRANCH = host.data.get("git_branch", "main")
TLS_CADDY_DATA_DIR = host.data.get("tls_caddy_data_dir", "/opt/tls/caddy")
TLS_CADDY_CONFIG_DIR = host.data.get("tls_caddy_config_dir", "/opt/tls/caddy-config")


def _allowed_telegram_ids() -> str:
    value = host.data.get("allowed_telegram_ids", "")
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


apt.packages(
    name="Install prerequisites",
    packages=["ca-certificates", "curl", "git"],
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

git.repo(
    name="Clone or update application from GitHub",
    src=GIT_REPO,
    dest=APP_DIR,
    branch=GIT_BRANCH,
    pull=True,
    ssh_keyscan=True,
    _sudo=True,
)

server.shell(
    name="Restore persisted cache after migration",
    commands=[
        f"mkdir -p {APP_DIR}/cache",
        (
            "test -d /tmp/bond-monitor-cache-migrate "
            f"&& cp -a /tmp/bond-monitor-cache-migrate/. {APP_DIR}/cache/ "
            "&& rm -rf /tmp/bond-monitor-cache-migrate || true"
        ),
    ],
    _sudo=True,
)

server.shell(
    name="Ensure shared TLS directories exist",
    commands=[
        f"mkdir -p {TLS_CADDY_DATA_DIR} {TLS_CADDY_CONFIG_DIR}",
        f"chmod 755 {TLS_CADDY_DATA_DIR} {TLS_CADDY_CONFIG_DIR}",
        (
            "docker volume inspect bond-monitor_caddy_data >/dev/null 2>&1 "
            f"&& docker run --rm -v bond-monitor_caddy_data:/from -v {TLS_CADDY_DATA_DIR}:/to "
            "alpine sh -c 'cp -an /from/. /to/' || true"
        ),
    ],
    _sudo=True,
)

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
    public_app_url=f"https://{host.data.domain}",
    telegram_oidc_client_id=host.data.get("telegram_oidc_client_id", ""),
    telegram_oidc_client_secret=host.data.get("telegram_oidc_client_secret", ""),
    allowed_telegram_ids=_allowed_telegram_ids(),
    notifier_scan_interval_sec=host.data.get("notifier_scan_interval_sec", 3600),
    telegram_bot_token=host.data.get("telegram_bot_token", ""),
    telegram_notify_user_id=host.data.get("telegram_notify_user_id", 0),
    image_tag=host.data.get("image_tag", "main"),
    tls_caddy_data_dir=TLS_CADDY_DATA_DIR,
    tls_caddy_config_dir=TLS_CADDY_CONFIG_DIR,
    _sudo=True,
)

if host.data.get("ghcr_token"):
    docker.login(
        name="Log in to GitHub Container Registry",
        server="ghcr.io",
        username=host.data.get("ghcr_username", ""),
        password=host.data["ghcr_token"],
        _sudo=True,
    )

docker.compose(
    name="Deploy Bond Monitor stack",
    project_directory=APP_DIR,
    project_name=PROJECT_NAME,
    files=COMPOSE_FILES,
    build=False,
    pull="always",
    _chdir=APP_DIR,
    _env={"IMAGE_TAG": host.data.get("image_tag", "main")},
    _sudo=True,
)
