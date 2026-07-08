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

### Первичная настройка

```bash
# 1. Скопировать и заполнить inventory (host, domain, токены)
cp deploy/inventory.py.example deploy/inventory.py

# 2. Установить task (go-task) и pyinfra
brew install go-task   # macOS; см. https://taskfile.dev/installation/
uv sync --group deploy
```

В `deploy/inventory.py` укажите IP сервера (без `user@`), `ssh_user`, домен и при необходимости токены. Репозиторий и ветка по умолчанию — в `deploy/group_data/all.py` (`git@github.com:tonatos/bond-monitor.git`, `main`).

```python
bond_monitor = (
    ["77.238.250.101"],  # только IP или hostname, не root@host
    {"ssh_user": "root", "domain": "bond.example.com", ...},
)
```

**Доступ VPS к GitHub (один раз):** на сервере нужен SSH-ключ с read-доступом к репозиторию.

```bash
ssh root@<VPS-IP>
ssh-keygen -t ed25519 -C "bond-monitor-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Публичный ключ добавьте в GitHub → репозиторий → Settings → Deploy keys (read-only).

### Docker-образы (GHCR)

Сборка образов — в **GitHub Actions** (`.github/workflows/docker.yml`), публикация в [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry):

- `ghcr.io/tonatos/bond-monitor-api:main`
- `ghcr.io/tonatos/bond-monitor-web:main`

На VPS образы только **скачиваются** (`docker compose pull`), без сборки.

После первого push в `main` дождитесь зелёного workflow **Docker**. Для приватных пакетов добавьте в `deploy/inventory.py` PAT с `read:packages` (`ghcr_username`, `ghcr_token`).

### Деплой

Из корня репозитория:

```bash
task deploy:dry   # предпросмотр
task deploy       # деплой
```

Таски описаны в [`Taskfile.yml`](Taskfile.yml) ([go-task](https://taskfile.dev/)).

Pyinfra на сервере:

1. Установит Docker и git (если отсутствуют)
2. Склонирует или обновит репозиторий в `/opt/bond-monitor` (`git pull`)
3. Сгенерирует `.env` из шаблона
4. Скачает образы из GHCR и запустит `docker compose up -d` (без `--build`)

### Проверка

- Web UI: `https://<DOMAIN>/`
- Health: `https://<DOMAIN>/health`

### Обновление

1. `git push` в `main` — GitHub Actions соберёт и опубликует образы в GHCR
2. `task deploy` — на VPS `git pull` + `docker compose pull` + перезапуск

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
