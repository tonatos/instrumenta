"""Shared defaults for all deployment targets."""

app_dir = "/opt/bond-monitor"
project_name = "bond-monitor"
compose_files = ["docker-compose.yml", "docker-compose.prod.yml"]
git_repo = "git@github.com:tonatos/bond-monitor.git"
git_branch = "main"
image_tag = "main"
ghcr_api_image = "ghcr.io/tonatos/bond-monitor-api"
ghcr_web_image = "ghcr.io/tonatos/bond-monitor-web"
