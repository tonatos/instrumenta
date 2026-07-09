# Bond Monitor — краткосрочные облигации РФ

Bond Monitor — веб-приложение для отбора и планирования портфеля краткосрочных облигаций РФ. Данные MOEX ISS, рейтингов и T-Invest собираются в единую базу; скринер ранжирует бумаги по YTM, ликвидности и риску. Планировщик автосоставляет портфель, прогнозирует cashflow, реинвестиции и XIRR до горизонта. В TRADING mode портфель сверяется со счётом брокера. Стек: Litestar API + React SPA.

![Портфель Bond Monitor](docs/portfolio-screenshot.png)

## Возможности

- **Скринер** — таблица ликвидных бумаг со скорингом YTM/риск/ликвидность
- **Избранное** — отслеживание выбранных ISIN
- **Портфель** — автосостав, прогноз cashflow, планирование до горизонта
- **Калькулятор** — расчёт доходности с учётом НДФЛ
- **Торговля** (TRADING mode) — интеграция T-Invest API (sandbox/production)

## Быстрый старт

### Docker (локально)

```bash
cp .env.example .env
docker compose up --build
```

- Web UI: http://localhost:3000
- API: http://localhost:8000/health

### Локальная разработка

```bash
# Backend
cp .env.example .env
uv sync --directory backend --extra dev --python 3.12
uv run --directory backend uvicorn bond_monitor.main:app --reload --port 8000

# Frontend (другой терминал)
cd frontend && npm install && npm run dev
```

- Web UI: http://localhost:5173 (прокси `/api` → `:8000`)

### Тесты

```bash
# Backend unit tests
uv run --directory backend pytest tests/unit -m "not sandbox"

# Sandbox integration (требует T_TRADING_TOKEN_SANDBOX)
T_TRADING_TOKEN_SANDBOX=t.xxx uv run --directory backend pytest tests/integration/sandbox -m sandbox

# Playwright e2e (нужен запущенный frontend + API)
cd e2e/playwright && npm install && npx playwright test
```

## Структура

```
backend/src/bond_monitor/   # Litestar API, DDD layers
frontend/src/               # React + Tailwind + shadcn-style UI
e2e/playwright/             # Webapp e2e tests
data/ratings.json           # Vendored credit ratings (read-only)
cache/                      # MOEX cache, SQLite DB, portfolios migration
```

Подробная архитектура — в [AGENTS.md](AGENTS.md).

## Деплой на VPS

Production-стек: **Caddy** (HTTPS, Let's Encrypt) → **nginx** (SPA + `/api` proxy) → **Litestar API** → **SQLite** (`cache/` volume).

### Требования

- VPS с Ubuntu/Debian, SSH-доступ по ключу
- DNS A-запись домена на IP сервера
- Открытые порты `80` и `443`

### Первичная настройка (один раз)

**1. GitHub Secrets** (Settings → Secrets and variables → Actions):

| Secret | Описание |
|--------|----------|
| `VPS_HOST` | IP сервера, напр. `77.238.250.101` |
| `VPS_USER` | SSH-пользователь, напр. `root` |
| `VPS_SSH_KEY` | Приватный SSH-ключ для доступа Actions → VPS |
| `GHCR_READ_TOKEN` | Опционально: PAT с `read:packages` для приватных образов |

Сгенерируйте отдельную пару ключей для CI (не используйте личный):

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/bond-monitor-gha -N ""
```

Публичный ключ (`bond-monitor-gha.pub`) → `authorized_keys` на VPS. Приватный → secret `VPS_SSH_KEY`.

**2. Bootstrap на VPS** (Docker, git clone, `.env` с секретами):

```bash
cp deploy/inventory.py.example deploy/inventory.py
# заполнить host, domain, токены

brew install go-task   # macOS
uv sync --group deploy
task deploy:bootstrap
```

Секреты (`TINKOFF_TOKEN`, `AUTH_SECRET`, OIDC и т.д.) записываются в `/opt/bond-monitor/.env` **только при bootstrap**. GitHub Actions их не трогает.

**3. Deploy key VPS → GitHub** (для `git pull` на сервере):

```bash
ssh root@<VPS-IP>
ssh-keygen -t ed25519 -C "bond-monitor-vps" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Публичный ключ → GitHub → репозиторий → Settings → Deploy keys (read-only).

### Docker-образы (GHCR)

Сборка — workflow **Docker** (push в `main`):

- `ghcr.io/tonatos/bond-monitor-api:main`
- `ghcr.io/tonatos/bond-monitor-web:main`

### Деплой (автоматический)

После успешной сборки workflow **Deploy** по SSH:

1. `git pull` в `/opt/bond-monitor`
2. `docker compose pull && up -d`
3. `.env` **не изменяется**

Ручной перезапуск: Actions → Deploy → Run workflow.

Локальный fallback (без GitHub):

```bash
task deploy:update
```

### Проверка

- Web UI: `https://<DOMAIN>/`
- Health: `https://<DOMAIN>/health`

### Общие TLS-сертификаты (Caddy)

Caddy хранит сертификаты на хосте в `/opt/tls/caddy` (bind-mount контейнера `/data`). При продлении ACME Caddy перезаписывает те же файлы — отдельный скрипт не нужен.

Пути к сертификату домена (после первого выпуска):

```
/opt/tls/caddy/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<DOMAIN>/<DOMAIN>.crt
/opt/tls/caddy/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<DOMAIN>/<DOMAIN>.key
```

Пример для другого docker-compose:

```yaml
volumes:
  - /opt/tls/caddy/caddy/certificates/acme-v02.api.letsencrypt.org-directory/example.com/example.com.crt:/etc/ssl/certs/site.pem:ro
  - /opt/tls/caddy/caddy/certificates/acme-v02.api.letsencrypt.org-directory/example.com/example.com.key:/etc/ssl/private/site.key:ro
```

### Обновление

1. `git push` в `main` → **Docker** (сборка) → **Deploy** (выкат на VPS)
2. Секреты на сервере меняйте вручную в `/opt/bond-monitor/.env`, затем `docker compose up -d`

### Бэкап

Сохраняйте volume `cache/` на сервере — в нём SQLite-база и MOEX-кэш:

```bash
tar czf bond-monitor-cache-$(date +%F).tar.gz -C /opt/bond-monitor cache/
```

### Ручной запуск production compose

```bash
DOMAIN=bond.example.com IMAGE_TAG=main docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
DOMAIN=bond.example.com IMAGE_TAG=main docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
