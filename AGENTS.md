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
    domain/trading (advisory, deploy_session, ports, …)
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
| Trading | `domain/trading/` | `infrastructure/tinvest/trading_client` + `snapshot_adapter`, `persistence/deploy_session_repository` |
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
| Trading queue (кнопки buy/sell) | Нет | `GET /trading-state` / `GET /advice` → suggestions; buy/reinvest — через **Deploy Session** |

**DRY:** детекция — `domain/notifications/rules.py`; доставка — `application/notifications/deliver_use_case.py`; рендер suggestions — `domain/notifications/suggestions.py`.

---

## Скрининг и скоринг

### Риск-профили (`RiskProfile`)

Три профиля: `conservative`, `normal`, `aggressive` (`domain/portfolio/models.py`).

| Профиль | Фильтр портфеля (`selection.risk_profile_filter`) | Веса YTM / риск / ликвидность |
|---------|---------------------------------------------------|-------------------------------|
| **conservative** | ≥ ruA, без `call_date`, без субординации / HIGH / безрейтинговых | 0.20 / 0.60 / 0.20 |
| **normal** | ≥ ruA−, без субординации / HIGH / безрейтинговых | 0.30 / 0.50 / 0.20 |
| **aggressive** | ≥ ruBB− (или без рейтинга) | 0.60 / 0.25 / 0.15 + boredom/junk penalties |

**Fallback при подборе** (`selection._fallback_steps`): `conservative → normal → любая без дефолта`; `aggressive → normal → любая без дефолта`; `normal → любая без дефолта`.

**Скринер не фильтрует universe по профилю** — селектор меняет только активный ключ в `profile_scores` (сортировка и колонка «Скор»). Фильтр по рейтингу применяется в `portfolio_universe_filter` при compose/reinvest.

### Два контура скоринга (`domain/screening/scorer.py`)

| Контур | Функция | Выборка YTM-шкалы | Дюрация |
|--------|---------|-------------------|---------|
| **Display** (скринер, API) | `score_bonds_all_profiles` | Полная universe (кэш screener/universe) | На чтении: `resolve_profile_scores` (без мутации `BondRecord`) |
| **Selection** (compose/reinvest) | `score_bonds_for_profile` | Подмножество кандидатов | Внутри функции, сразу в `bond.score` |

Компоненты (0–100): `ytm_score`, `risk_score`, `liquidity_score`. Базовые `profile_scores` (без дюрации) кэшируются в RAM после enrich; итоговый `score` и `profile_scores` в API = база + `duration_adjustment` (clamp 0–100).

**Единая точка отдачи в API:** `bond_to_response` → `resolve_profile_scores` + `duration_adjustment_for_bond`. Таблица скринера и `GET /bonds/{secid}` с теми же `risk_profile` + `rate_scenario` дают одинаковый скор.

### BondService (`application/bonds/bond_service.py`)

```
fetch MOEX → enrich (defaults, T-Invest, ratings, put offers)
         → score_bonds_all_profiles  →  RAM cache (screener / universe)
         → на чтении: clone_bond_record + sort_bonds_by_resolved_score / bond_to_response
```

| Метод | Поведение |
|-------|-----------|
| `load_screener_bonds` | Кэш screener; сортировка по resolved score активного профиля |
| `load_universe` | Все бумаги без volume/maturity фильтра — для YTM-шкалы |
| `load_by_secid` / `load_by_isins` | Сначала lookup в screener-кэше; вне окна — fetch + `_score_against_cached_universe` (шкала из universe) |
| `_clone_bonds` / `clone_bond_record` | Иммутабельность кэша при resolve duration |

Ликвидность и min-volume: `BondRecord.filter_volume_rub` = `prev_volume_rub` ?? `volume_rub` (вчерашний оборот MOEX предпочтительнее для фильтра и `liquidity_score`).

### `domain/screening/scorer.py` — ключевые функции

| Функция | Назначение |
|---------|------------|
| `score_bonds_all_profiles` | Базовые `profile_scores` для всех профилей (кэш) |
| `score_bonds_for_profile` | Скоринг подмножества кандидатов в selection pipeline |
| `resolve_profile_scores` | База + duration adjustment, без мутации bond |
| `sort_bonds_by_resolved_score` | Сортировка скринера по активному профилю |
| `bond_to_response` (serializers) | Единая отдача resolved scores в API |

### Bonds API — query params

| Параметр | Эндпоинты | Назначение |
|----------|-----------|------------|
| `risk_profile` | `GET /bonds/`, `/bonds/{secid}`, `/bonds/by-isins` | Активный профиль; `score` = `profile_scores[profile]` |
| `rate_scenario` | те же | `hold` / `cut` / `hike` → `DurationPolicy` → корректировка дюрации |
| `filter_by` | list | `effective` / `maturity` / `offer` — окно скринера |

`BondResponse`: `profile_scores` (все 3, с дюрацией), `score`, `duration_adjustment`, компоненты `ytm_score` / `risk_score` / `liquidity_score`, `volume_rub` + `prev_volume_rub`.

---

## Структура domain/portfolio

| Модуль | Ответственность |
|--------|-----------------|
| `auto_compose.py` | `auto_compose`, `compose_buy_allocations`, `sweep_remaining_cash` — единый алгоритм корзины; `compose_buy_allocations` учитывает `MAX_AUTO_POSITIONS` (10) с holdings |
| `deploy_cash.py` | **Единая** точка развёртывания кэша (план + advisory): `auto_compose` / `compose_buy_allocations` + sweep остатка |
| `simulation/` | Event-sourced симулятор: `state.py`, `events.py`, `engine.run_simulation()` — очередь событий, lazy lifecycle |
| `plan_builder.py` | Thin facade: `build_plan` → `run_simulation()`, read-model (слоты, XIRR, timeline) |
| `planner.py` | Facade: `auto_compose`, `compose_buy_allocations`, `deploy_cash`, `build_plan` |
| `selection.py` | Единый eligibility/ranking для compose и reinvest; `risk_profile_filter`, fallback-профили |
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
| `advisory.py` | Stateless `advise()`: holdings, suggestions, active orders, cashflow; buy — через `deploy_cash`; reinvest — `build_reinvest_suggestions` (actionable) + `build_reinvest_watch_suggestions` (информация); alert-suggestions через `collect_alerts()`; при `active_session` — buy/reinvest из frozen session |
| `deploy_session.py` | **Deploy Session** — краткоживущий снимок buy+reinvest: `build_deploy_session_plan`, `apply_session_staleness`, `sync_session_with_orders`, `session_items_to_suggestions`, lifecycle (`complete_session_if_no_pending`) |
| `holdings.py` | `HoldingView` — read-model позиции на счёте |
| `suggestions.py` | `Suggestion`, `SuggestionKind` — read-model рекомендаций |
| `models.py` | `AccountKind`, `FrozenForecast`, advisory DTO |
| `ports.py` | `BrokerSnapshot`, `BrokerOperation` — порты без SDK |
| `policies.py` | `DeploySessionPolicy` (TTL, price drift), буферы лимитных цен buy/sell |
| `ids.py` | `stable_id()` для детерминированных ключей заявок |
| `yield_calc.py` | XIRR из операций брокера |

Факт позиций на счёте — только из брокерского снапшота (`advice.holdings`), не из shadow-полей плана.

### SuggestionKind и секции UI

| Kind | Секция UI | Исполняемость |
|------|-----------|---------------|
| `buy`, `reinvest` | «Покупки» / «План закупки» | Только после **фиксации Deploy Session** (или внутри активной сессии) |
| `reinvest_watch` | «На контроле» | Информация до даты погашения источника (до 14 дней) |
| `put_offer_watch` | «На контроле» | Информация |
| `put_offer_reminder`, `sell` (risk) | «Срочно» | Live — без deploy session |

**Реинвестиция:** actionable `reinvest` — только когда `days_until <= 0` (кэш от погашения уже доступен); `reinvest_watch` — за 14 дней до погашения, без кнопки покупки.

---

## Deploy Session

Краткоживущая серверная «корзина» для атомарного исполнения buy+reinvest. Sell / put-offer / risk остаются **live** (вне сессии).

```
POST /deploy-sessions  →  build_deploy_session_plan()  →  SQLite deploy_sessions
         │
         ▼
advise(active_session=…)  →  buy/reinvest из session_items_to_suggestions
         │                  reinvest_watch + alerts — live
         ▼
place order (suggestion_id)  →  mark_item_placed  →  complete_session_if_no_pending
```

| Аспект | Поведение |
|--------|-----------|
| Persistence | `infrastructure/persistence/deploy_session_repository.py`, таблица `deploy_sessions` |
| TTL | `DeploySessionPolicy.ttl_hours` (24ч по умолчанию) |
| Конфликт | 409 при создании, если есть active session с pending items; lazy-complete если все placed/skipped |
| Staleness | `apply_session_staleness`: price drift, недоступная бумага, **преждевременный** reinvest (`due_date > today`), **просроченный** reinvest (`due_date < today`) |
| Frontend gate | `buyRequiresFrozenPlan` — кнопка «Подтвердить покупку» disabled без `deploy_session`; skip — только внутри сессии |

**Application:** `deploy_session_use_case.py` (create / refresh / cancel / skip / sync_active_session); хук в `order_use_case.py` при place.

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
├── trading_service.py          # тонкий DI-facade
├── trading_state_use_case.py   # GET /trading-state: plan + advice в одном broker round-trip
├── advise_use_case.py          # GET /advice (без MOEX refresh — это делает notifier)
├── deploy_session_use_case.py  # lifecycle frozen buy/reinvest плана
├── risk_monitoring.py          # acknowledge baseline (не proactive scan)
├── attach_use_case.py
├── order_use_case.py           # preview / place / cancel (+ deploy session hooks)
├── sell_position_use_case.py
├── sandbox_use_case.py
├── broker.py                   # единая точка I/O к T-Invest
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
| Bonds | `GET /bonds/?risk_profile=&rate_scenario=`, `GET /bonds/by-isins`, `GET /bonds/{secid}`, `POST /bonds/refresh` |
| Favorites | `GET/PUT/DELETE /favorites/{isin}` |
| Portfolios | CRUD `/portfolios/`, `POST .../auto-compose`, `GET .../plan` |
| Calculator | `POST /calculator/portfolio` |
| Trading | attach, `GET /advice`, **`GET /trading-state`**, **`POST/GET/DELETE /deploy-sessions`**, orders preview/place/cancel, sandbox, risk acknowledge, … |
| Notifications | `GET /portfolios/{id}/notifications`, `POST /notifications/{id}/read`, `POST /notifications/{id}/dismiss` |

**Trading-state:** `GET /portfolios/{id}/trading-state` — `{ plan, advice }`; `advice.deploy_session` — активная сессия (если есть). Фронтенд использует этот эндпоинт как единый источник для очереди действий и плана.

**Deploy sessions:**

| Метод | Путь | Назначение |
|-------|------|------------|
| POST | `/portfolios/{id}/deploy-sessions` | Зафиксировать план (201; 409 при pending session) |
| GET | `/portfolios/{id}/deploy-sessions/active` | Активная сессия |
| POST | `.../deploy-sessions/{sid}/refresh` | Пересобрать план |
| DELETE | `.../deploy-sessions/{sid}` | Отменить план |
| POST | `.../items/{item_id}/skip` | Пропустить позицию в плане |

`PortfolioResponse` включает `invested_capital_rub`, `positions_count`, `closed_positions_count` и типизированный `data: PortfolioDataResponse`.

DI: `Provide(get_db_session)`, `Provide(provide_bond_service)`, `Provide(provide_portfolio_service)`.

Запуск: `uv run --directory backend uvicorn bond_monitor.main:app --reload`

---

## Frontend

| Путь | Назначение |
|------|------------|
| `features/screener/ScreenerPage.tsx` | Таблица облигаций, селектор риск-профиля, объём (вчера крупно / сегодня мелко) |
| `features/screener/BondDetailSheet.tsx` | Деталка: компоненты скора + три карточки профилей (без дублирования «Итого») |
| `features/screener/screenerRiskProfile.ts` | `localStorage` активного профиля скринера |
| `features/bonds/bondScore.ts` | `bondScoreForProfile`, `PROFILE_SCORE_WEIGHTS` (зеркало backend) |
| `features/portfolio/PortfolioPage.tsx` | Оркестрация страницы |
| `features/portfolio/components/` | Form, PositionsTab, ForecastMetrics, … |
| `features/portfolio/hooks/usePortfolioQueries.ts` | Единый **`trading-state`** query (`tradingStateQueryKey`) для plan + advice |
| `features/portfolio/hooks/queryConfig.ts` | `STALE`, `tradingStateQueryKey` |
| `features/portfolio/trading/` | TradingActionQueue, `useDeploySession`, `useTradingAdvice`, ConfirmOrderDialog, OperationGroups, … |
| `features/portfolio/NotificationsPanel.tsx` | In-app уведомления из `GET /notifications` |
| `features/portfolio/labels.ts` | Единые label maps (не дублировать в компонентах) |
| `api/types.ts` | Ручное зеркало Pydantic DTO |

**Trading UI:** `OperationGroups.groupSuggestions()` — «Срочно» / «На контроле» (`put_offer_watch`, `reinvest_watch`) / «Покупки» (`buy`, `reinvest`). Mutations deploy session invalidate только `trading-state` query key.

**Скринер:** `risk_profile` и `rate_scenario` пробрасываются в `GET /bonds/` и `GET /bonds/{secid}`; сортировка по `bond.score` активного профиля. Портфель: `GET /bonds/by-isins?risk_profile=<portfolio.risk_profile>` для скора в позициях.

**Правило:** бизнес-логика только на backend. Frontend использует `invested_capital_rub`, `positions_count`, `GET /trading-state` для факта на счёте и очереди; pricing заявок — через `/orders/preview`.

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
└── mocked/               # wizard, queue, positions, notifications, deploy-session, …
```

**Не копируй** `_portfolio_client`, `_bond`, `_snapshot` в тестах — используй `factories.py` и `conftest.py`.

Покрытие deploy session: `test_deploy_session.py`, `test_reinvest_suggestions.py`, `test_deploy_session_repository.py`, `e2e/.../deploy-session.spec.ts`.

Покрытие скоринга: `test_scorer.py`, `test_bond_selection.py`, `test_api_bonds_risk_profile.py`, `test_api_bonds_score_consistency.py`, `test_screener_score_idempotency.py`, `e2e/.../screener-risk-profile.spec.ts`.

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
| Новый риск-профиль / веса скора | `RiskProfile` + `_PROFILE_WEIGHTS` в `scorer.py` + `risk_profile_filter` + `bondScore.ts` + API query param |
| Консистентность score list vs detail | Не пересчитывать изолированно: lookup из screener cache или `_score_against_cached_universe`; отдача через `bond_to_response` |
| Новый API endpoint | `interfaces/api/controllers/` + schema |
| Новая страница UI | `frontend/src/features/<name>/` + route в `App.tsx` |
| Новая политика планирования | `domain/portfolio/policies.py` |
| Новая торговая рекомендация (alert-driven) | `AlertRule` в `domain/notifications/rules.py` + `alerts_to_suggestions()` |
| Новый `SuggestionKind` (advisory) | `domain/trading/suggestions.py` + `advisory.py` + `labels.ts` + `OperationGroups` + `api/types.ts` |
| Deploy session / frozen plan | `domain/trading/deploy_session.py` + `deploy_session_use_case.py` + invalidate `trading-state` на фронте |
| Новый тип уведомления (push/UI) | `AlertRule` + `deliver_use_case.py` (если нужен новый канал) |
| Брокерский тип в domain | `domain/trading/ports.py` + adapter в infrastructure |
