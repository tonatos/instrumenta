# Bond Monitor — краткосрочные облигации РФ

Bond Monitor — веб-приложение для отбора и планирования портфеля краткосрочных облигаций РФ. Данные MOEX ISS, рейтингов и T-Invest собираются в единую базу; скринер ранжирует бумаги по YTM, ликвидности и риску. Планировщик автосоставляет портфель, прогнозирует cashflow, реинвестиции и XIRR до горизонта. В TRADING mode портфель сверяется со счётом брокера; фоновый **notifier** мониторит пут-оферты, риск эмитента и market signals, строит **Market Radar** по рынку, шлёт Telegram и публикует события в UI. Стек: **Go API** (`backend/cmd/api`) + **React SPA** + **Redis**.

**Лицензия:** [PolyForm Noncommercial 1.0.0](./LICENSE) — личное и некоммерческое использование; коммерческое использование, перепродажа и продукты на базе кода запрещены. Исходники: [github.com/tonatos/instrumenta](https://github.com/tonatos/instrumenta).


## На чём зарабатываем

- Купонный доход — основной источник, считается net после НДФЛ 13%.
- Дисконт к номиналу — покупка ниже 100% даёт доход при погашении (тоже с учётом налога на курсовую разницу).
- Реинвест — сложный процент: погашения и накопленный купонный кэш каждые ~30 дней уходят в новые лучшие бумаги (цепочка до 10 хопов).


![Портфель Bond Monitor](docs/portfolio-screenshot.png)

## Возможности

- **Скринер** — таблица ликвидных бумаг со скорингом YTM/риск/ликвидность, фильтр по секторам
- **Избранное** — отслеживание выбранных ISIN
- **Портфель** — автосостав, прогноз cashflow, планирование до горизонта; вкладка **«Сигналы»** (spread anomaly, sector stress, turbo-entry по **вашим** позициям)
- **Radar** (`/radar`) — read-model рынка: heatmap секторов Δ7д, топ аномалий спреда, dip-идеи (discovery по liquid universe)
- **Калькулятор** — расчёт доходности с учётом НДФЛ
- **Торговля** (TRADING mode) — интеграция T-Invest API (sandbox/production)
- **Уведомления** — фоновый воркер: пут-оферта, риск эмитента, market signals по holdings; Telegram + панели в UI

## Быстрый старт

### Docker (локально)

```bash
cp .env.example .env
docker compose up --build
```

Сервисы: `api`, `web`, `redis`, `notifier` (тот же образ, что у API). Notifier сканирует trading-портфели по расписанию и публикует события в Redis Stream; API читает шину и отдаёт их в UI.

- Web UI: http://localhost:3000
- API: http://localhost:8000/health

### Локальная разработка

Требования: Go 1.25+, Node.js 20+.

```bash
cp .env.example .env

# Backend (Go API, порт 8000)
task run:back
# или: cd backend && go run ./cmd/api

# Frontend (другой терминал)
task run:front

# Notifier (нужен Redis — в Docker он поднимается compose'ом;
# локально: docker compose up -d redis)
task run:notifier
```

- Web UI: http://localhost:5173 (прокси `/api` → `:8000`)
- Логи API: `LOG_LEVEL=DEBUG` в `.env` (structured `slog` в stdout)

Для Telegram-уведомлений и режима торговли добавьте в `.env`:

```env
T_TRADING_TOKEN_SANDBOX=...    # sandbox T-Invest (режим торговли)
TELEGRAM_BOT_TOKEN=...
# TELEGRAM_BOT_USERNAME=...    # опционально; иначе API берёт из getMe
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=DEBUG
```

### Тесты

```bash
# Backend: unit + golden HTTP tests
task test:back
# или: cd backend && go test ./...

# Frontend e2e (Playwright поднимает Go API + Vite сам)
task test:front

# Live e2e (нужен уже запущенный backend + frontend)
cd e2e/playwright && npx playwright test tests/live
```

**Trading / T-Invest:** mocked e2e не ходят в брокера (API мокается в браузере). Реальный sandbox — ручная проверка с `T_TRADING_TOKEN_SANDBOX` в `.env`.

## Структура

```
backend/
  cmd/api/                  # HTTP entrypoint
  cmd/notifier/             # фоновый воркер
  internal/
    domain/                 # чистая бизнес-логика
    application/            # use cases
    infrastructure/         # MOEX, T-Invest SDK, SQLite, Redis, Telegram
    interfaces/http/        # chi router, handlers, serializers
  testdata/golden/          # golden snapshots API-контракта
  migrations/               # SQL-миграции (001…003), применяются при старте API/notifier
frontend/src/               # React + Tailwind + shadcn-style UI
  features/radar/           # Market Radar (/radar)
e2e/playwright/             # Webapp e2e tests
**Ratings / defaults:** SQLite `bond_credit_ratings`, `bond_default_flags` (smart-lab + MOEX ISS); seed patterns in migration `004`.
cache/                      # MOEX cache, SQLite DB, notifier ledger
```

Подробная архитектура — в [AGENTS.md](AGENTS.md).

При обновлении кода перезапустите **api** и **notifier** — SQL-миграции из `backend/migrations/` применяются автоматически при старте (в т.ч. `spread_snapshots`, `market_radar_runs`).

## Notification worker

Фоновый процесс `notifier` периодически (по умолчанию раз в час, локально часто `60` сек) сканирует trading-портфели и **один раз за цикл** — market radar по liquid universe.

### Portfolio alerts (per-portfolio)

| Событие | Условие |
|---------|---------|
| Пут-оферта | Окно подачи **открыто**, решение `pending` |
| Риск эмитента | Эскалация относительно `risk_baselines` (дефолт, рейтинг и т.д.) |
| Spread anomaly / sector stress / turbo-entry | Market signals по **held** бумагам (`domain/market_signals`) |

### Market Radar (market-wide read-model)

После portfolio scan воркер вызывает `ScanMarketRadar`: upsert `spread_snapshots` для liquid universe → snapshot в `market_radar_runs`. API отдаёт **только read-model** (`GET /api/v1/market-radar`), без hot-path пересчёта.

| Секция radar | Когда появляется |
|--------------|------------------|
| **Аномалии спреда** | Сразу (cross-sectional vs peers) |
| **Heatmap секторов Δ7д** | После ~7 дней накопления `spread_snapshots` |
| **Dip-идеи** | Тоже требуют историю цен 7d |

**Каналы доставки (portfolio alerts):**

- **Telegram** — push на `owner_telegram_id` портфеля после `/start` в боте (critical risk + put-offer action; нужна подписка Pro / complimentary)
- **Redis Stream** → API consumer → `GET /api/v1/portfolios/{id}/notifications` (пут-оферта, риск, market signals по holdings)
- **Market Radar UI** — `GET /api/v1/market-radar` (без Telegram в v1)

Идемпотентность: ledger `cache/notifier_ledger.db` + fingerprint на событие. При недоступности Redis воркер пишет напрямую в SQLite.

Образ notifier = образ API (`ghcr.io/tonatos/bond-monitor-api`), другой `CMD`.

### Локальное тестирование уведомлений

1. В `.env`: `NOTIFICATIONS_DEV=true`, `AUTH_DISABLED=true`, `T_TRADING_TOKEN_SANDBOX`, `REDIS_URL`, `TELEGRAM_*`, `NOTIFIER_SCAN_INTERVAL_SEC=60`
2. `docker compose up -d redis` (или полный compose)
3. `task run:back` + `task run:front`
4. В UI: trading-портфель → sandbox account → attach → позиции на счёте
5. Зажечь тестовое событие и доставить:

```bash
# Пут-оферта (окно подачи OPEN)
task dev:notify:simulate -- put-offer --portfolio <portfolio_id>

# Ухудшение риска
task dev:notify:simulate -- risk-default --portfolio <portfolio_id>
task dev:notify:simulate -- risk-downgrade --portfolio <portfolio_id>

# Один проход scan → Redis + Telegram + GET /notifications
task dev:notify:scan

# Или daemon (тот же NOTIFICATIONS_DEV подмешивает overrides на каждом скане)
task run:notifier
```

Сброс ledger (повторная доставка того же fingerprint):

```bash
task dev:notify:reset
task dev:notify:reset -- --portfolio <portfolio_id>
```

Overrides пишутся в `cache/dev_notification_overrides.json`. Unit-тесты логики: `go test ./internal/dev/notifications/`.

## Деплой на VPS

Production-стек: **Caddy** (HTTPS, Let's Encrypt) → **nginx** (SPA + `/api` proxy) → **Go API** → **SQLite** (`cache/` volume). Параллельно: **Redis** (шина уведомлений) + **notifier** (фоновый мониторинг, тот же образ API).

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
cp deploy/inventory.example.yaml deploy/inventory.yaml
# заполнить host, domain, токены (если копируете с example)

brew install go-task   # macOS
task deploy:bootstrap
```

Секреты (`TINKOFF_TOKEN`, `AUTH_SECRET`, OIDC, `TELEGRAM_BOT_TOKEN` и т.д.) записываются в `/opt/bond-monitor/.env` **только при bootstrap**. GitHub Actions их не трогает.

Переменные notifier (см. `.env.example`):

| Переменная | Описание |
|------------|----------|
| `REDIS_URL` | Шина между notifier и API, напр. `redis://redis:6379/0` |
| `NOTIFIER_SCAN_INTERVAL_SEC` | Интервал скана (default `3600`) |
| `TELEGRAM_BOT_TOKEN` | Токен бота для push-уведомлений |
| `TELEGRAM_BOT_USERNAME` | Username бота для deep link (опционально; иначе getMe) |
| `NOTIFIER_LEDGER_PATH` | Путь к SQLite-ledger (default `cache/notifier_ledger.db`) |

**3. Deploy key VPS → GitHub** (для `git pull` на сервере):

```bash
ssh root@<VPS-IP>
ssh-keygen -t ed25519 -C "bond-monitor-vps" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Публичный ключ → GitHub → репозиторий → Settings → Deploy keys (read-only).

### Docker-образы (GHCR)

Сборка — workflow **Docker** (push в `main`):

- `ghcr.io/tonatos/bond-monitor-api:main` — API и notifier (один образ)
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

Сохраняйте volume `cache/` на сервере — в нём SQLite-база, MOEX-кэш и ledger notifier:

```bash
tar czf bond-monitor-cache-$(date +%F).tar.gz -C /opt/bond-monitor cache/
```

### Ручной запуск production compose

```bash
DOMAIN=bond.example.com IMAGE_TAG=main docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
DOMAIN=bond.example.com IMAGE_TAG=main docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
