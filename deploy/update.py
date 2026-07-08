"""Update Bond Monitor on VPS: git pull + compose pull (keeps existing .env)."""

from __future__ import annotations

from pyinfra import host
from pyinfra.operations import server

APP_DIR = host.data.app_dir
GIT_BRANCH = host.data.get("git_branch", "main")

server.shell(
    name="Update Bond Monitor on VPS",
    commands=[f"bash {APP_DIR}/deploy/scripts/remote-update.sh"],
    _env={
        "APP_DIR": APP_DIR,
        "IMAGE_TAG": host.data.get("image_tag", "main"),
        "GIT_BRANCH": GIT_BRANCH,
        "GHCR_USERNAME": host.data.get("ghcr_username", ""),
        "GHCR_TOKEN": host.data.get("ghcr_token", ""),
    },
    _sudo=True,
)
