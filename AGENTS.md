# AGENTS.md — Гайд по проекту bond-monitor для AI-агентов

Монорепозиторий: **Go API** (`backend/cmd/api`) + **React SPA** + **notifier worker** (`backend/cmd/notifier`). Читай этот файл перед изменениями кода.

---

## Архитектура

```
MOEX ISS ──► infrastructure/moex/ ──┐
T-Invest  ──► infrastructure/tinvest/ ──┤
smart-lab ──► infrastructure/ratings/ ──► SQLite bond_credit_ratings ──┘
                    ▼
         domain/bonds (BondRecord)
                    ▼
         domain/screening (scorer)
                    ▼
    domain/portfolio (planner, selection, cashflow, …)
    domain/trading (advisory, deploy_session, ports, …)
    domain/notifications (CollectAlerts, fingerprint)
    domain/market_signals (spread anomaly, attribution, radar scan)
                    ▼
         application/ (use cases)
                    ▼
    interfaces/http (chi)              cmd/notifier (воркер)
                    │                         │
                    │    portfolio scan + market radar scan
                    └──── Redis Stream ◄──────┘
                              ▼
                    infrastructure/persistence (SQLite read-model)
                              ▼
                        frontend/ (React)
```

### Multi-tenant (пользователи и ключи)

| Компонент | Поведение |
|-----------|----------|
| Identity | Telegram OIDC → JWT `sub` = telegram_id; при `AUTH_DISABLED` — `DEV_TELEGRAM_ID` |
| Ownership | `portfolios.owner_telegram_id`, favorites PK `(owner, isin)` |
| Broker keys | `broker_credentials` envelope AES-GCM + `BROKER_KEK`; API `PUT/DELETE /me/broker-credentials/{kind}` |
| Enrich | `TINKOFF_TOKEN` остаётся process env |
| Trading | `TokenFor(owner, kind)`; env `T_TRADING_TOKEN_*` только как fallback при `AUTH_DISABLED` |
| UI | `/account` — ключи + trust copy; wizard без ключей → «Настроить ключи» |
| Notifier | scan с токеном владельца; Telegram на `owner_telegram_id` |
| Isolation | чужой `portfolio_id` → 404; тесты `isolation_test.go`, e2e tenant |

`ALLOWED_TELEGRAM_IDS` пустой = любой Telegram-user (SaaS). Миграция `005_multi_tenant.sql` + `EnsureMultiTenantSchema`.

### DDD-слои (`backend/internal/`)

| Слой | Путь | Ответственность |
|------|------|-----------------|
| **Domain** | `internal/domain/` | Чистая бизнес-логика, без I/O |
| **Application** | `internal/application/` | Use cases, оркестрация |
| **Infrastructure** | `internal/infrastructure/` | MOEX, T-Invest, SQL, Redis, file cache |
| **Interfaces** | `internal/interfaces/` | HTTP handlers, auth, config |
| **Entrypoints** | `cmd/api`, `cmd/notifier` | HTTP server + фоновый воркер |

**Legacy:** `backend/src/bond_monitor/` — устаревший Python-код (reference), **не используется в runtime**. Активный backend только Go (`backend/cmd`, `backend/internal`).

### Bounded contexts

| Context | Domain | Infrastructure |
|---------|--------|----------------|
| Bond Screening | `domain/bonds`, `domain/screening` | `infrastructure/moex`, `infrastructure/ratings`, `infrastructure/tinvest` |
| Portfolio Planning | `domain/portfolio/` | — (pure) |
| Trading | `domain/trading/` | `infrastructure/tinvest`, `persistence/deploy_session_repository` |
| Notifications | `domain/notifications/` | `infrastructure/notifications/` (Redis, ledger, Telegram) |
| Market signals / Radar | `domain/market_signals/` | `persistence/spread_snapshots`, `persistence/market_radar_repository` |
| Persistence | Repository interfaces | `infrastructure/persistence` |

**Важно:** domain **не импортирует** infrastructure. Брокерские read-model типы — `domain/trading/ports.go`; порт I/O — `broker_port.go`; маппинг в `infrastructure/tinvest/snapshot_adapter.go`.

### Границы notifier vs API

| Слой | Notifier (воркер) | API |
|------|-------------------|-----|
| Детекция алертов | По расписанию (`scan`) | On-demand в `Advise()` через `CollectAlerts()` |
| MOEX defaults refresh | Да, при скане | Нет (убрано из hot-path advise) |
| `sync_risk_baselines` | Да, при скане | Только через `acknowledge` endpoint |
| Telegram push | **Только воркер** | Нет |
| Публикация в шину | **Только воркер** | Consumer при старте → SQLite |
| Trading queue (кнопки buy/sell) | Нет | `GET /trading-state` / `GET /advice` → suggestions; buy/reinvest — через **Deploy Session** |
| Market radar scan | 1× за цикл после portfolio scans | **Нет** — только `GET /market-radar` read-model |

**DRY:** детекция portfolio alerts — `domain/notifications/rules.go`; market-wide radar — `domain/market_signals/radar_scan.go`; доставка — `application/notifications/deliver_use_case.go`; рендер suggestions — `domain/notifications/suggestions.go`.

### Два контура сигналов (не смешивать)

| Контур | UI | Источник | Для кого |
|--------|-----|----------|----------|
| **Portfolio signals** | Вкладка «Сигналы» на `PortfolioPage` | `user_notifications` по `portfolio_id` | Что происходит с **моими** позициями |
| **Market radar** | Страница `/radar` | `market_radar_runs` (JSON snapshot) | Что происходит на **рынке** |

Radar **не считает** ничего в API hot-path — worker → SQLite → render-only frontend.

---

## Скрининг и скоринг

### Риск-профили (`RiskProfile`)

Три профиля: `conservative`, `normal`, `aggressive` (`domain/portfolio/models.go`).

| Профиль | Фильтр портфеля (`selection.risk_profile_filter`) | Веса YTM / риск / ликвидность |
|---------|---------------------------------------------------|-------------------------------|
| **conservative** | ≥ ruA, без `call_date`, без субординации / HIGH / безрейтинговых | 0.20 / 0.60 / 0.20 |
| **normal** | ≥ ruA−, без субординации / HIGH / безрейтинговых | 0.30 / 0.50 / 0.20 |
| **aggressive** | ≥ ruBB− (или без рейтинга) | 0.60 / 0.25 / 0.15 + boredom/junk penalties |

**Fallback при подборе** (`selection.FallbackSteps`): `conservative → normal → любая без дефолта`; `aggressive → normal → любая без дефолта`; `normal → любая без дефолта`.

**Скринер не фильтрует universe по профилю** — селектор меняет только активный ключ в `profile_scores` (сортировка и колонка «Скор»). Фильтр по рейтингу применяется в `portfolio_universe_filter` при compose/reinvest.

### Два контура скоринга (`domain/screening/scorer.go`)

| Контур | Функция | Выборка YTM-шкалы | Дюрация |
|--------|---------|-------------------|---------|
| **Display** (скринер, API) | `score_bonds_all_profiles` | Полная universe (кэш screener/universe) | На чтении: `resolve_profile_scores` (без мутации `BondRecord`) |
| **Selection** (compose/reinvest) | `score_bonds_for_profile` | Подмножество кандидатов | Внутри функции, сразу в `bond.score` |

Компоненты (0–100): `ytm_score`, `risk_score`, `liquidity_score`. Базовые `profile_scores` (без дюрации) кэшируются в RAM после enrich; итоговый `score` и `profile_scores` в API = база + `duration_adjustment` (clamp 0–100).

**Единая точка отдачи в API:** `bond_to_response` → `resolve_profile_scores` + `duration_adjustment_for_bond`. Таблица скринера и `GET /bonds/{secid}` с теми же `risk_profile` + `rate_scenario` дают одинаковый скор.

### BondService (`application/bonds/bond_service.go`)

```
fetch MOEX (unfiltered) → enrich (defaults, T-Invest, ratings, put offers)
                        → score_bonds_all_profiles → RAM universe cache
                        → ListBonds(query): filter + sort + paginate in-memory
```

| Метод | Поведение |
|-------|-----------|
| `LoadUniverse` | Единственный enriched cache (~all MOEX bonds); warm at startup |
| `ListBonds` | `domain/bonds.FilterBondList` + `SortBondList` + `PaginateBondList` поверх universe |
| `LoadBySecid` / `LoadByISINs` | Lookup из universe cache; вне кэша — fetch + score against cached universe |
| `cloneBondRecord` | Иммутабельность кэша при resolve duration |

**Ratings:** smart-lab scrape → `bond_credit_ratings` (ISIN, source=`smartlab`); fallback `issuer_rating_patterns`; manual override `source=manual`. Refresh: `POST /ratings/refresh` + auto if stale >7d.

**Defaults:** MOEX ISS `HASDEFAULT`/`HASTECHNICALDEFAULT` → `bond_default_flags` (source=`moex`, TTL 24h); manual override `source=manual`. Таблицы в `bond_monitor.db`, миграция `004_bond_reference.sql`.

Ликвидность и min-volume: `BondRecord.filter_volume_rub` = `prev_volume_rub` ?? `volume_rub` (вчерашний оборот MOEX предпочтительнее для фильтра и `liquidity_score`).

### `domain/bonds/screener_query.go`

| Функция | Назначение |
|---------|------------|
| `FilterBondList` | Фильтры скринера по полям модели (`HideDefault` → flags, `HideSubordinated` → `SubordinatedFlag`, volume, days, YTM, …) |
| `SortBondList` | Серверная сортировка; `score` через `screening` + `risk_profile` / `rate_scenario` |
| `PaginateBondList` | Offset/limit по `page` / `page_size` (default 50, max 100) |

### `domain/screening/scorer.go` — ключевые функции

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
| `filter_by` | list | `effective` / `maturity` — окно дней до погашения |
| `max_days`, `min_volume_rub`, `min_ytm_net`, `max_lot_price_rub` | list | Серверные фильтры скринера (опциональны; `GET /config/` — только UI defaults) |
| `coupon_types`, `risk_levels`, `sectors` | list | CSV-списки (секторы — raw keys, labels на фронте) |
| `hide_default`, `hide_subordinated` | list | `true` — скрыть по `HasDefault`/`HasTechnicalDefault` и `SubordinatedFlag` |
| `q` | list | Поиск по name/secid/isin |
| `sort_by`, `sort_desc` | list | Серверная сортировка (`score`, `ytm_net`, `days_to_maturity`, …) |
| `page`, `page_size` | list | Пагинация (default 50); `export=true` — все совпадения (cap 5000) |

`BondsListResponse`: `bonds`, `total`, `page`, `page_size`, `count` (len страницы), `source`.

`BondResponse`: `profile_scores` (все 3, с дюрацией), `score`, `duration_adjustment`, компоненты `ytm_score` / `risk_score` / `liquidity_score`, `volume_rub` + `prev_volume_rub`.

---

## Структура domain/portfolio

| Модуль | Ответственность |
|--------|-----------------|
| `auto_compose.go` | `AutoCompose`, `ComposeBuyAllocations`, `SweepRemainingCash` — единый алгоритм корзины; `ComposeBuyAllocations` учитывает `MaxAutoPositions` (10) с holdings |
| `deploy_cash.go` | **Единая** точка развёртывания кэша (план + advisory): `AutoCompose` / `ComposeBuyAllocations` + sweep остатка |
| `simulation/` | Event-sourced симулятор: `state.go`, `events.go`, `RunSimulation()` — очередь событий, lazy lifecycle |
| `plan_builder.go` | Thin facade: `BuildPlan` → `RunSimulation()`, read-model (слоты, XIRR, timeline) |
| `planner.go` | Facade: `AutoCompose`, `ComposeBuyAllocations`, `DeployCash`, `BuildPlan` |
| `selection.go` | Единый eligibility/ranking для compose и reinvest; `RiskProfileFilter`, fallback-профили |
| `position_factory.go` | `PositionFromBond`, `PositionEndDate` |
| `coupon_schedule.go` | Расписание купонов |
| `cashflow.go` | `CashflowEvent`, merge helpers |
| `put_offer.go` | Единые правила пут-оферт |
| `risk_monitor.go` | `DetectRiskEscalations`, `SyncRiskBaselines`, `RiskSnapshot` |
| `invested_capital.go` | `InvestedCapitalRub()` для API |
| `position_status.go` | Статус позиции для API (план); факт на счёте — в advice |
| `policies.go` | `PlanningPolicy`, `BondSelectionPolicy`, … |

---

## Структура domain/trading

| Модуль | Ответственность |
|--------|-----------------|
| `advisory.go` | Stateless `Advise()`: holdings, suggestions, active orders, cashflow; buy — через `DeployCash`; reinvest — actionable + watch; alert-suggestions через `CollectAlerts()`; при `active_session` — buy/reinvest из frozen session |
| `deploy_session.go` | **Deploy Session** — краткоживущий снимок buy+reinvest: `BuildDeploySessionPlan`, `ApplySessionStaleness`, `SyncSessionWithOrders`, `SessionItemsToSuggestions`, lifecycle |
| `holdings.go` | `HoldingView` — read-model позиции на счёте |
| `suggestions.go` | `Suggestion`, `SuggestionKind` — read-model рекомендаций |
| `models.go` | `AccountKind`, `FrozenForecast`, advisory DTO |
| `ports.go` | `BrokerSnapshot`, `BrokerOperation` — порты без SDK |
| `broker_port.go` | `BrokerClient` interface + infra DTO (`InfraAccountSnapshot`, …) |
| `policies.go` | `DeploySessionPolicy` (TTL, price drift), буферы лимитных цен buy/sell |
| `ids.go` | `StableID()` для детерминированных ключей заявок |
| `yield_calc.go` | XIRR из операций брокера |

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
POST /deploy-sessions  →  BuildDeploySessionPlan()  →  SQLite deploy_sessions
         │
         ▼
Advise(active_session=…)  →  buy/reinvest из SessionItemsToSuggestions
         │                  reinvest_watch + alerts — live
         ▼
place order (suggestion_id)  →  mark item placed  →  CompleteSessionIfNoPending
```

| Аспект | Поведение |
|--------|-----------|
| Persistence | `infrastructure/persistence/deploy_session_repository.go`, таблица `deploy_sessions` |
| TTL | `DeploySessionPolicy.TTLHours` (24ч по умолчанию) |
| Конфликт | 409 при создании, если есть active session с pending items; lazy-complete если все placed/skipped |
| Staleness | `ApplySessionStaleness`: price drift, недоступная бумага, **преждевременный** reinvest (`due_date > today`), **просроченный** reinvest (`due_date < today`) |
| Frontend gate | `buyRequiresFrozenPlan` — кнопка «Подтвердить покупку» disabled без `deploy_session`; skip — только внутри сессии |

**Application:** `deploy_session_use_case.go` (create / refresh / cancel / skip / sync); хук в `order_use_case.go` при place.

---

## Структура domain/notifications

Единая точка детекции событий и расширения правил.

| Модуль | Ответственность |
|--------|-----------------|
| `models.go` | `Alert`, `AlertKind` (`put_offer_action`, `risk_escalation`, `put_offer_watch`) |
| `rules.go` | `CollectAlerts()`, `AlertRule` interface, `WorkerAlertRules` vs `DefaultAlertRules` |
| `fingerprint.go` | `AlertFingerprint()`, cooldown для Telegram |
| `policies.go` | `NotificationPolicy` (cooldown, min urgency для Telegram) |
| `suggestions.go` | `AlertsToSuggestions()` — маппинг в trading queue |

**Правила v1 (воркер):**
- Пут-оферта — только `put_offer_submit_due` (окно OPEN, decision `pending`)
- Риск — `DetectRiskEscalations()`; Telegram только `critical`, в шину — все sell-эскалации

Новое правило = новый `AlertRule` в `rules.go` + unit-тест. Delivery pipeline не трогать.

---

## Структура domain/market_signals

Pure domain: **без** импортов из `portfolio` / `trading` / `notifications`.

| Модуль | Ответственность |
|--------|-----------------|
| `policies.go` | `SpreadAnomalyPolicy`, `MarketRadarPolicy` |
| `attribution.go` | Δ7д бумаги / сектора / рынка, `Interpretation` |
| `rank_anomalies.go` | Cross-sectional spread anomaly vs peers |
| `rank_dip_ideas.go` | `RankDipIdeas`, `BuildSectorHeatmap` |
| `radar_scan.go` | `ScanMarketRadar` — orchestration |
| `radar_universe.go` | `FilterRadarUniverse` (liquid, no default, min volume) |

**Application:** `application/market_signals/`
- `scan_radar_use_case.go` — notifier: universe → upsert `spread_snapshots` → `ScanMarketRadar` → `market_radar_runs`
- `get_radar_use_case.go` — API: latest run + optional `in_portfolios` overlay из plan positions

**Persistence:**
- `spread_snapshots` — daily credit spread + last price (holdings + radar universe)
- `market_radar_runs` — `id`, `scanned_at`, `universe_count`, `payload_json` (sectors, anomalies, dip_ideas)

**Radar scan (воркер):** liquid universe (~500–1500) → anomaly ranking сразу; heatmap/dip ideas — только при наличии snapshot **7d назад** в `spread_snapshots`.

**Portfolio market signals** (spread_anomaly, sector_stress, turbo_entry) детектируются в notifier для **held** bonds и пишутся в `user_notifications`; те же аномалии могут дублироваться в radar anomalies для discovery.

---

## Application layer (trading)

```
application/trading/
├── trading_service.go          # тонкий DI-facade
├── trading_state_use_case.go   # GET /trading-state: plan + advice в одном broker round-trip
├── advise_use_case.go          # GET /advice
├── deploy_session_use_case.go  # lifecycle frozen buy/reinvest плана
├── risk_monitoring.go          # acknowledge baseline (не proactive scan)
├── attach_use_case.go
├── order_use_case.go           # preview / place / cancel (+ deploy session hooks)
├── sell_position_use_case.go
├── sandbox_use_case.go
├── broker_client.go            # wiring tinvest.SDKClient
└── context.go                  # BrokerFacade + token resolution
```

## T-Invest (`infrastructure/tinvest/`)

| Модуль | Ответственность |
|--------|-----------------|
| `client.go` | `SDKClient` — реализация `domain/trading.BrokerClient` |
| `snapshot.go` | `GetAccountSnapshot` — portfolio + positions |
| `orders.go` | preview / limit / cancel / active orders |
| `instruments.go` | FIGI, trade availability, last price |
| `operations.go` | история операций (cursor pagination) |
| `sandbox.go` | open/close/pay-in sandbox |
| `snapshot_adapter.go` | infra DTO → `BrokerSnapshot` |
| `enrichment.go` | `ReadClient` — enrich bonds (MOEX fallback если нет токена) |

SDK: `github.com/russianinvestments/invest-api-go-sdk`. Endpoints: sandbox `sandbox-invest-public-api.tbank.ru:443`, production `invest-public-api.tbank.ru:443`. Токены: `T_TRADING_TOKEN_SANDBOX` / `T_TRADING_TOKEN_PRODUCTION`.

**Тесты не ловят отсутствие брокера:** mocked Playwright перехватывает `/api/v1/...`; golden/unit не ходят в T-Invest. Регрессия заглушек — `client_test.go` (`not yet wired`). Sandbox — ручная проверка.

## Application layer (notifications)

```
application/notifications/
├── scan_use_case.go        # scan trading portfolios → CollectAlerts → deliver → radar scan
├── deliver_use_case.go     # ledger → Redis / SQLite fallback → Telegram
└── consumer.go             # Redis Stream consumer при старте API
```

## Application layer (market_signals)

```
application/market_signals/
├── scan_radar_use_case.go  # notifier: ScanMarketRadar + persist
└── get_radar_use_case.go   # API: Get + portfolio ISIN overlay
```

## Notifier worker

```
backend/cmd/notifier/main.go   # scan loop
internal/application/notifications/
```

Запуск: `go run ./cmd/notifier` (из `backend/`) или `task run:notifier`. Образ Docker = образ API, другой `CMD` (`/app/notifier`).

Цикл: `ListAll()` trading-портфелей → broker snapshot → `SyncRiskBaselines` → `CollectAlerts(WorkerAlertRules)` → deliver → **`ScanRadarUseCase.Run`** (market radar).

**Миграции:** при старте API/notifier `app/runMigrations` применяет все `backend/migrations/*.sql` по порядку (`001_initial`, `002_spread_snapshots`, `003_market_radar`, …).

## Infrastructure (notifications)

| Модуль | Ответственность |
|--------|-----------------|
| `redis_bus.go` | Redis Stream `bond-monitor:notifications`, consumer group `api` |
| `ledger_repository.go` | SQLite outbox `cache/notifier_ledger.db`, идемпотентность |
| `notifications_repository.go` | Read-model `user_notifications` в `bond_monitor.db` |
| `telegram_client.go` | Telegram Bot API push |

При недоступности Redis воркер пишет напрямую в `user_notifications`.

## Логирование

| Компонент | Поведение |
|-----------|-----------|
| `interfaces/logging/logger.go` | `slog` из `LOG_LEVEL` / `DEBUG` |
| `cmd/api/main.go` | старт: конфиг, токены (флаги), Redis, bond cache |
| `interfaces/http/middleware.go` | HTTP access log (method, path, status, duration); `/health` без лога |
| `infrastructure/tinvest/` | SDK logger через `SetLogger()` в `app/wire.go` |

Stdout — structured text (`slog`). Docker: `docker compose logs -f api`.

---

## API (Go / chi)

Базовый префикс: `/api/v1`

Handlers: `internal/interfaces/http/handlers_*.go`, router — `router.go`, DTO — `dto.go`, serializers — `serializers.go`.

| Группа | Эндпоинты |
|--------|-----------|
| Config | `GET /config/` |
| Bonds | `GET /bonds/?…filters&page=&page_size=`, `GET /bonds/by-isins`, `GET /bonds/{secid}`, `POST /bonds/refresh` |
| Favorites | `GET/PUT/DELETE /favorites/{isin}` |
| Portfolios | CRUD `/portfolios/`, `POST .../auto-compose`, `GET .../plan` |
| Calculator | `POST /calculator/portfolio` |
| Market radar | `GET /market-radar?highlight_portfolios=true` |
| Trading | attach, `GET /advice`, **`GET /trading-state`**, **`POST/GET/DELETE /deploy-sessions`**, orders preview/place/cancel, sandbox, risk acknowledge, … |
| Notifications | `GET /portfolios/{id}/notifications`, `POST /notifications/{id}/read`, `POST /notifications/{id}/dismiss` |

**Market radar:** `GET /market-radar` — latest `market_radar_runs`; `highlight_portfolios` (default `true`) добавляет `in_portfolios: string[]` по ISIN из plan positions всех портфелей. Labels секторов — на фронте (`sectorLabels.ts`), API отдаёт raw `sector` keys.

**Trading-state:** `GET /portfolios/{id}/trading-state` — `{ plan, advice }`; `advice.deploy_session` — активная сессия (если есть). Фронтенд использует этот эндпоинт как единый источник для очереди действий и плана.

**Deploy sessions:**

| Метод | Путь | Назначение |
|-------|------|------------|
| POST | `/portfolios/{id}/deploy-sessions` | Зафиксировать план (201; 409 при pending session) |
| GET | `/portfolios/{id}/deploy-sessions/active` | Активная сессия |
| POST | `.../deploy-sessions/{sid}/refresh` | Пересобрать план |
| DELETE | `.../deploy-sessions/{sid}` | Отменить план |
| POST | `.../items/{item_id}/skip` | Пропустить позицию в плане |

`PortfolioResponse` включает `invested_capital_rub`, `positions_count`, `closed_positions_count` и типизированный `data`.

DI: `app/wire.go` → `httpapi.Deps` (bonds, portfolios, trading, notifications, **market radar**, JWT).

Запуск: `go run ./cmd/api` (из `backend/`, порт 8000) или `task run:back`

---

## Frontend

| Путь | Назначение |
|------|------------|
| `features/screener/ScreenerPage.tsx` | Таблица облигаций: `useInfiniteQuery` + IntersectionObserver, серверные фильтры/сортировка |
| `features/screener/screenerQuery.ts` | Сбор query params для `GET /bonds/` |
| `features/screener/useDebouncedValue.ts` | Debounce 300ms для текстовых/числовых фильтров |
| `features/screener/BondDetailSheet.tsx` | Деталка: компоненты скора + три карточки профилей (без дублирования «Итого») |
| `features/screener/screenerRiskProfile.ts` | `localStorage` активного профиля скринера |
| `features/bonds/sectorLabels.ts` | `sectorLabel`, `SECTOR_FILTER_OPTIONS` — DRY labels секторов |
| `features/bonds/bondScore.ts` | `bondScoreForProfile`, `PROFILE_SCORE_WEIGHTS` (зеркало backend) |
| `features/portfolio/PortfolioPage.tsx` | Оркестрация страницы; вкладки через `PortfolioTabs` |
| `features/portfolio/SignalsPanel.tsx` | Market signals по портфелю (вкладка «Сигналы», trading only) |
| `features/portfolio/NotificationsPanel.tsx` | Пут-оферты / риск (без market signals) |
| `features/portfolio/marketSignals.ts` | `MARKET_SIGNAL_KINDS`, фильтр notifications → signals |
| `features/radar/RadarPage.tsx` | Market Radar: heatmap, anomalies, dip ideas |
| `features/radar/useMarketRadar.ts` | Query + sort «Сначала мои» |
| `features/portfolio/components/` | Form, PositionsTab, SectorExposurePanel, … |
| `features/portfolio/hooks/usePortfolioQueries.ts` | Единый **`trading-state`** query (`tradingStateQueryKey`) для plan + advice |
| `features/portfolio/hooks/queryConfig.ts` | `STALE`, `tradingStateQueryKey` |
| `features/portfolio/trading/` | TradingActionQueue, `useDeploySession`, `useTradingAdvice`, ConfirmOrderDialog, OperationGroups, … |
| `features/portfolio/NotificationsPanel.tsx` | In-app уведомления из `GET /notifications` |
| `features/portfolio/labels.ts` | Единые label maps (не дублировать в компонентах) |
| `api/types.ts` | Ручное зеркало API DTO (Go serializers) |

**Trading UI:** `OperationGroups.groupSuggestions()` — «Срочно» / «На контроле» (`put_offer_watch`, `reinvest_watch`) / «Покупки» (`buy`, `reinvest`). Mutations deploy session invalidate только `trading-state` query key.

**Скринер:** фильтры и сортировка — только через query params `GET /bonds/` (новый запрос при изменении); infinite scroll по 50 бумаг. `risk_profile`, `rate_scenario`, `sectors` (CSV). `max_days` / `min_volume_rub` из `GET /config/` — начальные значения UI, не серверные константы. Портфель: `GET /bonds/by-isins?risk_profile=<portfolio.risk_profile>`.

**Radar UI:** route `/radar`, nav «Radar»; heatmap клик → фильтр сектора; toggle «Сначала мои» (client sort по `in_portfolios`); dip idea → deep link в портфель или скринер. Stale time query: 5 min.

**Правило:** бизнес-логика только на backend. Frontend использует `invested_capital_rub`, `positions_count`, `GET /trading-state` для факта на счёте и очереди; pricing заявок — через `/orders/preview`.

---

## Тестирование

### Инфраструктура

```
backend/
├── internal/domain/              # unit-тесты (_test.go рядом с кодом)
├── internal/infrastructure/      # persistence, tinvest, moex
├── internal/interfaces/http/     # golden_test.go — контракт API
└── testdata/golden/              # JSON snapshots

e2e/playwright/tests/
├── fixtures.ts                   # mockConfig, makeTradingPortfolio, …
├── live/                         # smoke (нужен API)
└── mocked/                       # wizard, queue, deploy-session, …
```

Golden snapshots: `backend/testdata/golden/` — эталон HTTP-контракта (регрессия при рефакторинге handlers).

Покрытие deploy session: `domain/trading/deploy_session_test.go`, `e2e/.../deploy-session.spec.ts`.

Покрытие скоринга: `domain/screening/scorer_test.go`, `domain/bonds/screener_query_test.go`, `e2e/.../screener-risk-profile.spec.ts`, `e2e/.../screener-filters.spec.ts`.

Покрытие market radar: `domain/market_signals/radar_scan_test.go`, `application/market_signals/get_radar_use_case_test.go`, golden `market_radar_empty.json`, `e2e/.../market-radar.spec.ts`.

### Команды

```bash
# Unit + golden HTTP tests
cd backend && go test ./...

# Notifier (нужен Redis)
task run:notifier

# Playwright e2e (mocked — webServer поднимает go API + vite)
cd e2e/playwright && npx playwright test tests/mocked

# Playwright live (нужен backend + frontend)
cd e2e/playwright && npx playwright test tests/live
```

Golden snapshots: `backend/testdata/golden/` (эталон HTTP-контракта API).

---

## Деплой (Docker Compose)

Сервисы: `api`, `web`, `redis`, `notifier`, опционально `caddy` (prod). Notifier и API — один образ `bond-monitor-api`.

Env notifier (общий `.env`): `REDIS_URL`, `NOTIFIER_SCAN_INTERVAL_SEC`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NOTIFY_USER_ID`, `NOTIFIER_LEDGER_PATH`.

---

## Конвенции рефакторинга

- **KISS** — минимальный diff, без over-engineering
- **DRY** — shared helpers в domain, `labels.ts`, `testdata/`
- **SRP** — один модуль = одна ответственность; God modules разбивать
- **Low coupling** — domain без infrastructure imports; frontend без дублирования pricing
- **TDD** — новые фичи: unit/domain + e2e бизнес-сценарии

---

## Политики планирования

```go
type PlanningPolicy struct {
    ReinvestmentGapDays   int
    PutOfferReminderDays  int
    MaxReinvestDepth      int
    // см. domain/portfolio/policies.go
}
```

Политики передаются явно в use cases.

---

## Расширение

| Задача | Куда |
|--------|------|
| Новый источник данных | `infrastructure/<source>/` + enrich в `BondService` |
| Новый риск-профиль / веса скора | `RiskProfile` + weights в `scorer.go` + `RiskProfileFilter` + `bondScore.ts` + API query param |
| Консистентность score list vs detail | Lookup из universe cache; отдача через `serializers.go` |
| Новый API endpoint | `interfaces/http/handlers_*.go` + `dto.go` + golden test |
| Новая страница UI | `frontend/src/features/<name>/` + route в `App.tsx` |
| Новая политика планирования | `domain/portfolio/policies.go` |
| Новая торговая рекомендация (alert-driven) | `AlertRule` в `domain/notifications/rules.go` + `AlertsToSuggestions()` |
| Новый `SuggestionKind` (advisory) | `domain/trading/suggestions.go` + `advisory.go` + `labels.ts` + `OperationGroups` + `api/types.ts` |
| Deploy session / frozen plan | `domain/trading/deploy_session.go` + `deploy_session_use_case.go` + invalidate `trading-state` на фронте |
| Новый тип уведомления (push/UI) | `AlertRule` + `deliver_use_case.go` (если нужен новый канал) |
| Брокерский тип в domain | `domain/trading/ports.go` / `broker_port.go` + adapter в `infrastructure/tinvest/` |
| T-Invest SDK метод | `infrastructure/tinvest/*.go` + `broker_port.go` если новый порт |
| Market radar rule / threshold | `domain/market_signals/policies.go` + `radar_scan_test.go` |
| Новая SQL-таблица | `backend/migrations/NNN_*.sql` + inline schema в `portfolio_repository.ApplyMigrations` для тестов |
| Radar UI widget | `frontend/src/features/radar/` + `api/types.ts` + e2e |
