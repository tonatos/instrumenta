# AGENTS.md — Гайд по проекту bond-monitor для AI-агентов

Монорепозиторий: **Litestar API** + **React SPA**. Читай этот файл перед изменениями кода.

---

## Архитектура

```
MOEX ISS ──► infrastructure/moex/ ──┐
T-Invest  ──► infrastructure/tinvest/ ──┤
smart-lab ──► infrastructure/ratings/ ──┘
                    ▼
         domain/bonds (BondRecord)
                    ▼
         domain/screening (scorer)
                    ▼
    domain/portfolio (planner, models)
    domain/trading (reconciler, pending, yield)
                    ▼
         application/ (use cases)
                    ▼
         interfaces/api (Litestar controllers)
                    ▼
              frontend/ (React)
```

### DDD-слои (`backend/src/bond_monitor/`)

| Слой | Путь | Ответственность |
|------|------|-----------------|
| **Domain** | `domain/` | Чистая бизнес-логика, без I/O |
| **Application** | `application/` | Use cases, оркестрация |
| **Infrastructure** | `infrastructure/` | MOEX, T-Invest, SQLAlchemy, file cache |
| **Interfaces** | `interfaces/` | HTTP API, Pydantic DTOs, Settings |

### Bounded contexts

| Context | Domain | Infrastructure |
|---------|--------|----------------|
| Bond Screening | `domain/bonds`, `domain/screening` | `infrastructure/moex`, `infrastructure/ratings`, `tinvest/read_client` |
| Portfolio Planning | `domain/portfolio` | — (pure) |
| Trading | `domain/trading` | `infrastructure/tinvest/trading_client` |
| Persistence | Repository interfaces | `infrastructure/persistence` |

---

## Структура монорепо

```
bond-monitor/
├── backend/                  # Python API (uv, Litestar)
│   ├── src/bond_monitor/
│   └── tests/
├── frontend/                 # React + TypeScript + Tailwind
├── e2e/playwright/           # Webapp e2e
├── data/ratings.json         # Vendored ratings (RO in Docker)
├── cache/                    # MOEX cache, SQLite DB, migration source
├── pyproject.toml            # uv workspace root
└── docker-compose.yml        # api + web (+ postgres profile)
```

---

## Ключевые типы

- `BondRecord` (`domain/bonds/models.py`) — единая модель облигации
- `Portfolio` / `PortfolioPosition` (`domain/portfolio/models.py`)
- `PortfolioPlan` (`domain/portfolio/planner.py`) — производный прогноз
- `PlanningPolicy` / `ScoringPolicy` — параметризованные правила (без magic globals)
- `Rub` / `PriceUnitPct` / `Lots` (`domain/shared/money.py`)

---

## Политики планирования

```python
@dataclass(frozen=True)
class PlanningPolicy:
    reinvestment_gap_days: int = 2
    max_position_share: float = 0.30
    target_position_share: float = 0.18
    # см. domain/portfolio/policies.py
```

Политики передаются явно в use cases. Planner **не пишет на диск** — `_clear_slot_override` только in-memory; persistence в application layer.

---

## API (Litestar)

Базовый префикс: `/api/v1`

| Группа | Эндпоинты |
|--------|-----------|
| Config | `GET /config/` |
| Bonds | `GET /bonds/`, `GET /bonds/{secid}`, `POST /bonds/refresh` |
| Favorites | `GET/PUT/DELETE /favorites/{isin}` |
| Portfolios | CRUD `/portfolios/`, `POST .../auto-compose`, `GET .../plan` |
| Calculator | `POST /calculator/portfolio` |
| Ratings | `POST /ratings/refresh` |

DI: `Provide(get_db_session)`, `Provide(provide_bond_service)`, `Provide(provide_portfolio_service)`.

Запуск: `uv run --directory backend uvicorn bond_monitor.main:app --reload`

---

## Persistence

- **SQLite** (default): `sqlite+aiosqlite:///./cache/bond_monitor.db`
- **Postgres**: `postgresql+asyncpg://...` через `DATABASE_URL`
- При первом запуске: миграция `cache/portfolios.json` и `favorites.json` → DB (`json_migration.py`)
- MOEX disk cache остаётся file-based (`cache/moex_bonds.pkl`)

---

## Frontend

| Технология | Назначение |
|------------|------------|
| React 19 + TypeScript | UI |
| Tailwind CSS v4 | Стили |
| TanStack Query | Server state |
| TanStack Table | Скринер |
| React Router v7 | Маршруты |
| Recharts | Cashflow chart |

Страницы: `/` (скринер), `/favorites`, `/portfolio`, `/calculator`.

Компоненты UI: `frontend/src/components/ui/` (shadcn-style).

API client: `frontend/src/api/client.ts` — прокси через Vite dev server.

---

## Переменные окружения

| Имя | Описание |
|-----|----------|
| `TINKOFF_TOKEN` | T-Invest read-only |
| `T_TRADING_TOKEN_SANDBOX` | Sandbox trading |
| `T_TRADING_TOKEN_PRODUCTION` | Production trading |
| `KEY_RATE`, `TAX_RATE`, `MAX_DAYS`, `MIN_VOLUME_RUB` | Скоринг |
| `DATABASE_URL` | SQLite/Postgres |
| `CACHE_DIR` | Override cache path |

---

## Портфель — бизнес-правила

См. прежнюю документацию по алгоритмам (актуально в `domain/portfolio/planner.py`):

- `auto_compose` — диверсификация (TARGET/MAX/MIN position share)
- `build_plan` — cashflow, реинвест-цепочки, put-offer, held at horizon
- `validate_replacement_bond` — guard от «денег из воздуша»
- `distribute_top_up` — распределение пополнения

Константы → `PlanningPolicy` в `domain/portfolio/policies.py`.

---

## Режим торговли (TRADING)

Логика в `domain/trading/` + `infrastructure/tinvest/trading_client.py`:

- `portfolio_reconciler` — attach validation, reconcile, top-up detection
- `pending_operations` — генерация pending BUY/SELL/put-offer
- `yield_calc` — XIRR из операций (`pyxirr`)

**Примечание:** TRADING UI endpoints (attach, confirm order) — расширяйте `interfaces/api/controllers.py` и `frontend/features/portfolio/`.

---

## Тестирование

```bash
# Unit (без сети)
uv run --directory backend pytest tests/unit -m "not sandbox"

# Sandbox integration
T_TRADING_TOKEN_SANDBOX=t.xxx uv run --directory backend pytest tests/integration/sandbox -m sandbox

# Playwright e2e
cd e2e/playwright && npx playwright test
```

Покрытие P0: `test_planner.py`, `test_scorer.py`, trading-модули, reconciler, pending, yield, money.

---

## Команды разработки

```bash
# Python
uv sync --directory backend --extra dev --python 3.12
uv run --directory backend ruff check . --fix
uv run --directory backend ruff format .

# Frontend
cd frontend && npm run dev
cd frontend && npm run build

# Docker
docker compose up --build
docker compose --profile postgres up  # с Postgres
```

---

## Конвенции

- Python 3.12+, ruff format/lint, mypy strict на domain/application
- TypeScript strict, Prettier для frontend
- Domain layer: **без** импортов из infrastructure/interfaces
- Application layer: оркестрация, без HTTP-деталей
- Новые поля облигации → `BondRecord`, не промежуточные dict

---

## Расширение

| Задача | Куда |
|--------|------|
| Новый источник данных | `infrastructure/<source>/` + enrich в `BondService` |
| Новый API endpoint | `interfaces/api/controllers.py` + schema |
| Новая страница UI | `frontend/src/features/<name>/` + route в `App.tsx` |
| Новая политика планирования | `domain/portfolio/policies.py` |
| Новый pending kind | `domain/trading/pending_operations.py` |
