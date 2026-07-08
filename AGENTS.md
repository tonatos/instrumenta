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
    domain/portfolio (planner, selection, cashflow, …)
    domain/trading (advisory, ports, models)
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
| Portfolio Planning | `domain/portfolio/` | — (pure) |
| Trading | `domain/trading/` | `infrastructure/tinvest/trading_client` + `snapshot_adapter` |
| Persistence | Repository interfaces | `infrastructure/persistence` |

**Важно:** domain **не импортирует** infrastructure. Брокерские типы — `domain/trading/ports.py` (`BrokerSnapshot`, `BrokerOperation`); маппинг в `infrastructure/tinvest/snapshot_adapter.py`.

---

## Структура domain/portfolio

| Модуль | Ответственность |
|--------|-----------------|
| `planner.py` | Facade: `auto_compose`, `build_plan`, `distribute_top_up` |
| `selection.py` | Единый eligibility/ranking для compose, reinvest, top-up |
| `position_factory.py` | `position_from_bond`, `position_end_date` |
| `coupon_schedule.py` | Расписание купонов |
| `cashflow.py` | `CashflowEvent`, merge helpers |
| `put_offer.py` | Единые правила пут-оферт |
| `invested_capital.py` | `invested_capital_rub()` для API |
| `position_status.py` | Статус позиции для API (план); факт на счёте — в advice |
| `policies.py` | `PlanningPolicy`, `BondSelectionPolicy`, … |

---

## Структура domain/trading

| Модуль | Ответственность |
|--------|-----------------|
| `advisory.py` | Stateless `advise()`: holdings, suggestions, active orders, cashflow |
| `models.py` | `AccountKind`, `FrozenForecast`, advisory DTO |
| `ports.py` | `BrokerSnapshot`, `BrokerOperation` — порты без SDK |
| `ids.py` | `stable_id()` для детерминированных ключей заявок |
| `yield_calc.py` | XIRR из операций брокера |

Факт позиций на счёте — только из брокерского снапшота (`advice.holdings`), не из shadow-полей плана.

---

## Application layer (trading)

```
application/trading/
├── trading_service.py    # тонкий DI-facade
├── advise_use_case.py      # GET /advice
├── attach_use_case.py
├── order_use_case.py       # preview / place / cancel
├── sell_position_use_case.py
├── sandbox_use_case.py
├── broker.py               # единая точка I/O к T-Invest
└── context.py
```

---

## API (Litestar)

Базовый префикс: `/api/v1`

Контроллеры разбиты: `interfaces/api/controllers/bonds.py`, `portfolio.py`, `trading.py`.

| Группа | Эндпоинты |
|--------|-----------|
| Config | `GET /config/` |
| Bonds | `GET /bonds/`, `GET /bonds/{secid}`, `POST /bonds/refresh` |
| Favorites | `GET/PUT/DELETE /favorites/{isin}` |
| Portfolios | CRUD `/portfolios/`, `POST .../auto-compose`, `GET .../plan` |
| Calculator | `POST /calculator/portfolio` |
| Trading | attach, `GET /advice`, orders preview/place/cancel, sandbox, … |

`PortfolioResponse` включает `invested_capital_rub`, `positions_count`, `closed_positions_count` и типизированный `data: PortfolioDataResponse`.

DI: `Provide(get_db_session)`, `Provide(provide_bond_service)`, `Provide(provide_portfolio_service)`.

Запуск: `uv run --directory backend uvicorn bond_monitor.main:app --reload`

---

## Frontend

| Путь | Назначение |
|------|------------|
| `features/portfolio/PortfolioPage.tsx` | Оркестрация страницы |
| `features/portfolio/components/` | Form, PositionsTab, ForecastMetrics, … |
| `features/portfolio/trading/` | TradingActionQueue, `useTradingAdvice`, ConfirmOrderDialog, … |
| `features/portfolio/labels.ts` | Единые label maps (не дублировать в компонентах) |
| `api/types.ts` | Ручное зеркало Pydantic DTO |

**Правило:** бизнес-логика только на backend. Frontend использует `invested_capital_rub`, `positions_count`, `GET /advice` для факта на счёте; pricing заявок — через `/orders/preview`.

---

## Тестирование

### Инфраструктура

```
backend/tests/
├── conftest.py           # client, portfolio_client, attach_trading_portfolio
├── factories.py          # make_bond, make_account_snapshot, aa19dfd_*
└── unit/
    ├── domain/           # planner, advisory, …
    ├── api/              # test_api_*
    ├── infrastructure/   # moex, tinvest, serializers
    └── application/

e2e/playwright/tests/
├── fixtures.ts           # mockConfig, makeTradingPortfolio, …
├── live/                 # smoke, features (нужен API)
└── mocked/               # wizard, queue, positions, …
```

**Не копируй** `_portfolio_client`, `_bond`, `_snapshot` в тестах — используй `factories.py` и `conftest.py`.

### Команды

```bash
# Unit (без сети)
uv run --directory backend pytest tests/unit -m "not sandbox"

# Sandbox integration
T_TRADING_TOKEN_SANDBOX=t.xxx uv run --directory backend pytest tests/integration/sandbox -m sandbox

# Playwright e2e (mocked — без API)
cd e2e/playwright && npx playwright test tests/mocked

# Playwright live (нужен backend + frontend)
cd e2e/playwright && npx playwright test tests/live
```

Покрытие P0: `test_planner.py`, `test_scorer.py`, `test_trading_advisory.py`, yield.

---

## Конвенции рефакторинга

- **KISS** — минимальный diff, без over-engineering
- **DRY** — shared helpers в `factories.py`, `put_offer.py`, `labels.ts`
- **SRP** — один модуль = одна ответственность; God modules разбивать
- **Low coupling** — domain без infrastructure imports; frontend без дублирования pricing
- **TDD** — новые фичи: unit/domain + e2e бизнес-сценарии

---

## Политики планирования

```python
@dataclass(frozen=True)
class PlanningPolicy:
    reinvestment_gap_days: int = 2
    put_offer_reminder_days: int = 30
    max_reinvest_depth: int = 10
    # см. domain/portfolio/policies.py
```

Политики передаются явно в use cases.

---

## Расширение

| Задача | Куда |
|--------|------|
| Новый источник данных | `infrastructure/<source>/` + enrich в `BondService` |
| Новый API endpoint | `interfaces/api/controllers/` + schema |
| Новая страница UI | `frontend/src/features/<name>/` + route в `App.tsx` |
| Новая политика планирования | `domain/portfolio/policies.py` |
| Новая торговая рекомендация | `domain/trading/advisory.py` + `advise_use_case.py` |
| Брокерский тип в domain | `domain/trading/ports.py` + adapter в infrastructure |
