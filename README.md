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

# 2. Установить pyinfra
uv sync --group deploy

# 3. Перейти в каталог deploy (для group_data и относительных путей)
cd deploy
```

В `deploy/inventory.py` укажите SSH-пользователя, домен и при необходимости T-Invest токены.

### Деплой

```bash
cd deploy

# Предпросмотр изменений
uv run pyinfra inventory.py deploy.py --dry

# Деплой
uv run pyinfra inventory.py deploy.py
```

Pyinfra на сервере:

1. Установит Docker (если отсутствует)
2. Синхронизирует исходники в `/opt/bond-monitor`
3. Сгенерирует `.env` из шаблона
4. Запустит `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`

### Проверка

- Web UI: `https://<DOMAIN>/`
- Health: `https://<DOMAIN>/health`

### Обновление

Повторите команду деплоя — pyinfra пересинхронизирует файлы и пересоберёт образы.

### Бэкап

Сохраняйте volume `cache/` на сервере — в нём SQLite-база и MOEX-кэш:

```bash
tar czf bond-monitor-cache-$(date +%F).tar.gz -C /opt/bond-monitor cache/
```

### Ручной запуск production compose

```bash
DOMAIN=bond.example.com docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
