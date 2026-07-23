#!/usr/bin/env bash
# Run on VPS: git pull + pull images + compose up. Does not modify .env.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/instrumenta}"
IMAGE_TAG="${IMAGE_TAG:-main}"
GIT_BRANCH="${GIT_BRANCH:-main}"

cd "$APP_DIR"

if [[ ! -d .git ]]; then
  echo "ERROR: ${APP_DIR} is not a git repository. Run deploy bootstrap first." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "ERROR: ${APP_DIR}/.env not found. Run deploy bootstrap first." >&2
  exit 1
fi

git fetch origin "$GIT_BRANCH"
git reset --hard "origin/${GIT_BRANCH}"

if [[ -n "${GHCR_TOKEN:-}" && -n "${GHCR_USERNAME:-}" ]]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
fi

export IMAGE_TAG

# Optional TSPU bypass: hysteria overlay when client config is present on the VPS.
COMPOSE_ARGS=(-f docker-compose.yml -f docker-compose.prod.yml)
if [[ -f hysteria-client.yaml ]]; then
  COMPOSE_ARGS+=(-f docker-compose.hysteria.yml)
fi

docker compose "${COMPOSE_ARGS[@]}" pull
docker compose "${COMPOSE_ARGS[@]}" up -d --remove-orphans

docker compose "${COMPOSE_ARGS[@]}" ps
