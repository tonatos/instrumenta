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

### Docker

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
