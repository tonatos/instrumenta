# AGENTS.md — Гайд по проекту bond-monitor для AI-агентов

Монорепозиторий: **Litestar API** + **React SPA** + **notifier worker** (фоновый мониторинг). Читай этот файл перед изменениями кода.

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
    domain/notifications (collect_alerts, fingerprint)
                    ▼
         application/ (use cases)
                    ▼
    interfaces/api (Litestar)          notifier/ (фоновый воркер)
                    │                         │
                    └──── Redis Stream ◄──────┘
                              ▼
                    infrastructure/persistence (SQLite read-model)
                              ▼
                        frontend/ (React)
```

### DDD-слои (`backend/src/bond_monitor/`)

| Слой | Путь | Ответственность |
|------|------|-----------------|
| **Domain** | `domain/` | Чистая бизнес-логика, без I/O |
| **Application** | `application/` | Use cases, оркестрация |
| **Infrastructure** | `infrastructure/` | MOEX, T-Invest, SQLAlchemy, Redis, file cache |
| **Interfaces** | `interfaces/` | HTTP API, Pydantic DTOs, Settings |
| **Notifier** | `notifier/` | Entrypoint фонового воркера (`python -m bond_monitor.notifier`) |

### Bounded contexts

| Context | Domain | Infrastructure |
|---------|--------|----------------|
| Bond Screening | `domain/bonds`, `domain/screening` | `infrastructure/moex`, `infrastructure/ratings`, `tinvest/read_client` |
| Portfolio Planning | `domain/portfolio/` | — (pure) |
| Trading | `domain/trading/` | `infrastructure/tinvest/trading_client` + `snapshot_adapter` |
| Notifications | `domain/notifications/` | `infrastructure/notifications/` (Redis, ledger, Telegram) |
| Persistence | Repository interfaces | `infrastructure/persistence` |

**Важно:** domain **не импортирует** infrastructure. Брокерские типы — `domain/trading/ports.py` (`BrokerSnapshot`, `BrokerOperation`); маппинг в `infrastructure/tinvest/snapshot_adapter.py`.

### Границы notifier vs API

| Слой | Notifier (воркер) | API |
|------|-------------------|-----|
| Детекция алертов | По расписанию (`scan_use_case`) | On-demand в `advise()` через тот же `collect_alerts()` |
| MOEX defaults refresh | Да, при скане | Нет (убрано из hot-path advise) |
| `sync_risk_baselines` | Да, при скане | Только через `acknowledge` endpoint |
| Telegram push | **Только воркер** | Нет |
| Публикация в шину | **Только воркер** | Consumer при старте → SQLite |
| Trading queue (кнопки buy/sell) | Нет | `GET /advice` → `alerts_to_suggestions()` |

**DRY:** детекция — `domain/notifications/rules.py`; доставка — `application/notifications/deliver_use_case.py`; рендер suggestions — `domain/notifications/suggestions.py`.

---

## Структура domain/portfolio

| Модуль | Ответственность |
|--------|-----------------|
| `auto_compose.py` | `auto_compose`, `compose_buy_allocations`, `sweep_remaining_cash` — единый алгоритм корзины; `compose_buy_allocations` учитывает `MAX_AUTO_POSITIONS` (10) с holdings |
| `deploy_cash.py` | **Единая** точка развёртывания кэша (план + advisory): `auto_compose` / `compose_buy_allocations` + sweep остатка |
| `simulation/` | Event-sourced симулятор: `state.py`, `events.py`, `engine.run_simulation()` — очередь событий, lazy lifecycle |
| `plan_builder.py` | Thin facade: `build_plan` → `run_simulation()`, read-model (слоты, XIRR, timeline) |
| `planner.py` | Facade: `auto_compose`, `compose_buy_allocations`, `deploy_cash`, `build_plan` |
| `selection.py` | Единый eligibility/ranking для compose и reinvest |
| `position_factory.py` | `position_from_bond`, `position_end_date` |
| `coupon_schedule.py` | Расписание купонов |
| `cashflow.py` | `CashflowEvent`, merge helpers |
| `put_offer.py` | Единые правила пут-оферт |
| `risk_monitor.py` | `detect_risk_escalations`, `sync_risk_baselines`, `RiskSnapshot` |
| `invested_capital.py` | `invested_capital_rub()` для API |
| `position_status.py` | Статус позиции для API (план); факт на счёте — в advice |
| `policies.py` | `PlanningPolicy`, `BondSelectionPolicy`, … |

---

## Структура domain/trading

| Модуль | Ответственность |
|--------|-----------------|
| `advisory.py` | Stateless `advise()`: holdings, suggestions, active orders, cashflow; buy — через `deploy_cash`; alert-suggestions через `collect_alerts()` |
| `holdings.py` | `HoldingView` — read-model позиции на счёте |
| `suggestions.py` | `Suggestion`, `SuggestionKind` — read-model рекомендаций |
| `models.py` | `AccountKind`, `FrozenForecast`, advisory DTO |
| `ports.py` | `BrokerSnapshot`, `BrokerOperation` — порты без SDK |
| `ids.py` | `stable_id()` для детерминированных ключей заявок |
| `yield_calc.py` | XIRR из операций брокера |

Факт позиций на счёте — только из брокерского снапшота (`advice.holdings`), не из shadow-полей плана.

---

## Структура domain/notifications

Единая точка детекции событий и расширения правил.

| Модуль | Ответственность |
|--------|-----------------|
| `models.py` | `Alert`, `AlertKind` (`put_offer_action`, `risk_escalation`, `put_offer_watch`) |
| `rules.py` | `collect_alerts()`, `AlertRule` protocol, `WORKER_ALERT_RULES` vs `DEFAULT_ALERT_RULES` |
| `fingerprint.py` | `alert_fingerprint()`, cooldown для Telegram |
| `policies.py` | `NotificationPolicy` (cooldown, min urgency для Telegram) |
| `suggestions.py` | `alerts_to_suggestions()` — маппинг в trading queue |

**Правила v1 (воркер):**
- Пут-оферта — только `put_offer_submit_due` (окно OPEN, decision `pending`)
- Риск — `detect_risk_escalations()`; Telegram только `critical`, в шину — все sell-эскалации

Новое правило = новый `AlertRule` в `rules.py` + unit-тест. Delivery pipeline не трогать.

---

## Application layer (trading)

```
application/trading/
├── trading_service.py      # тонкий DI-facade
├── advise_use_case.py      # GET /advice (без MOEX refresh — это делает notifier)
├── risk_monitoring.py      # acknowledge baseline (не proactive scan)
├── attach_use_case.py
├── order_use_case.py       # preview / place / cancel
├── sell_position_use_case.py
├── sandbox_use_case.py
├── broker.py               # единая точка I/O к T-Invest
└── context.py
```

## Application layer (notifications)

```
application/notifications/
├── scan_use_case.py        # scan trading portfolios → collect_alerts → deliver
├── deliver_use_case.py     # ledger → Redis / SQLite fallback → Telegram
└── consumer.py             # Redis Stream consumer при старте API
```

## Notifier worker

```
notifier/
├── __main__.py             # asyncio loop, scan interval
└── settings.py             # NOTIFIER_*, REDIS_URL, TELEGRAM_*
```

Запуск: `python -m bond_monitor.notifier` или `task run:notifier`. Образ Docker = образ API, другой `CMD`.

Цикл: `list_all()` trading-портфелей → broker snapshot → MOEX defaults → `sync_risk_baselines` → `collect_alerts(WORKER_ALERT_RULES)` → deliver.

## Infrastructure (notifications)

| Модуль | Ответственность |
|--------|-----------------|
| `redis_bus.py` | Redis Stream `bond-monitor:notifications`, consumer group `api` |
| `ledger_repository.py` | SQLite outbox `cache/notifier_ledger.db`, идемпотентность |
| `notifications_repository.py` | Async read-model `user_notifications` в `bond_monitor.db` |
| `telegram_client.py` | Telegram Bot API push |

При недоступности Redis воркер пишет напрямую в `user_notifications`.

---

## API (Litestar)

Базовый префикс: `/api/v1`

Контроллеры разбиты: `interfaces/api/controllers/bonds.py`, `portfolio.py`, `trading.py`, `notifications.py`.

| Группа | Эндпоинты |
|--------|-----------|
| Config | `GET /config/` |
| Bonds | `GET /bonds/`, `GET /bonds/{secid}`, `POST /bonds/refresh` |
| Favorites | `GET/PUT/DELETE /favorites/{isin}` |
| Portfolios | CRUD `/portfolios/`, `POST .../auto-compose`, `GET .../plan` |
| Calculator | `POST /calculator/portfolio` |
| Trading | attach, `GET /advice`, orders preview/place/cancel, sandbox, risk acknowledge, … |
| Notifications | `GET /portfolios/{id}/notifications`, `POST /notifications/{id}/read`, `POST /notifications/{id}/dismiss` |

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
| `features/portfolio/NotificationsPanel.tsx` | In-app уведомления из `GET /notifications` |
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
    ├── domain/           # planner, advisory, notifications, …
    ├── api/              # test_api_*
    ├── infrastructure/   # moex, tinvest, serializers
    └── application/

e2e/playwright/tests/
├── fixtures.ts           # mockConfig, makeTradingPortfolio, …
├── live/                 # smoke, features (нужен API)
└── mocked/               # wizard, queue, positions, notifications, …
```

**Не копируй** `_portfolio_client`, `_bond`, `_snapshot` в тестах — используй `factories.py` и `conftest.py`.

### Команды

```bash
# Unit (без сети)
uv run --directory backend pytest tests/unit -m "not sandbox"

# Sandbox integration
T_TRADING_TOKEN_SANDBOX=t.xxx uv run --directory backend pytest tests/integration/sandbox -m sandbox

# Notifier (нужен Redis)
task run:notifier

# Playwright e2e (mocked — без API)
cd e2e/playwright && npx playwright test tests/mocked

# Playwright live (нужен backend + frontend)
cd e2e/playwright && npx playwright test tests/live
```

Покрытие P0: `test_planner.py`, `test_plan_simulation.py`, `test_scorer.py`, `test_trading_advisory.py`, `test_notification_rules.py`, yield.

---

## Деплой (Docker Compose)

Сервисы: `api`, `web`, `redis`, `notifier`, опционально `caddy` (prod). Notifier и API — один образ `bond-monitor-api`.

Env notifier (общий `.env`): `REDIS_URL`, `NOTIFIER_SCAN_INTERVAL_SEC`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NOTIFY_USER_ID`, `NOTIFIER_LEDGER_PATH`.

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
| Новая торговая рекомендация | `AlertRule` в `domain/notifications/rules.py` + `alerts_to_suggestions()` |
| Новый тип уведомления (push/UI) | `AlertRule` + `deliver_use_case.py` (если нужен новый канал) |
| Брокерский тип в domain | `domain/trading/ports.py` + adapter в infrastructure |
