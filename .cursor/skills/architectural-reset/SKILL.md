---
name: architectural-reset-bond-monitor
description: >-
  Project overlay for architectural-reset in bond-monitor. Applies DDD layer
  constraints and unified entry points from AGENTS.md. Use together with the
  personal architectural-reset skill when working in this repository.
disable-model-invocation: true
---

# Architectural Reset — bond-monitor overlay

**Сначала** прочитай и следуй персональному скиллу:
`~/.cursor/skills/architectural-reset/SKILL.md`

Затем примени ограничения этого репозитория. Полный контекст — [`AGENTS.md`](../../../AGENTS.md).

---

## DDD-слои (`backend/src/bond_monitor/`)

| Слой | Путь | Правило reset |
|------|------|---------------|
| Domain | `domain/` | Чистая логика, **без I/O**; не импортирует infrastructure |
| Application | `application/` | Use cases, оркестрация |
| Infrastructure | `infrastructure/` | MOEX, T-Invest, SQLAlchemy, Redis |
| Interfaces | `interfaces/` | HTTP API, Pydantic DTOs |
| Notifier | `notifier/` | Фоновый воркер |

**Dependency rule:** `domain/` → ничего из `infrastructure/`, `interfaces/`, SDK.

Брокерские типы — только `domain/trading/ports.py`; маппинг — `infrastructure/tinvest/snapshot_adapter.py`.

---

## Unified entry points (расширять, не дублировать)

Перед созданием нового модуля проверь, можно ли расширить:

| Задача | Единая точка |
|--------|--------------|
| Развёртывание кэша (план + advisory) | `domain/portfolio/deploy_cash.py` |
| Корзина / аллокации | `auto_compose`, `compose_buy_allocations` в `auto_compose.py` |
| Eligibility / ranking | `domain/portfolio/selection.py` |
| Пут-оферты | `domain/portfolio/put_offer.py` |
| Детекция алертов | `domain/notifications/rules.py` → `collect_alerts()` |
| Маппинг в trading queue | `domain/notifications/suggestions.py` |
| Доставка уведомлений | `application/notifications/deliver_use_case.py` |
| Trading advisory | `domain/trading/advisory.py` → `advise()` |
| UI labels | `frontend/src/features/portfolio/labels.ts` |

Новое правило алерта = новый `AlertRule` в `rules.py` + unit-тест. Delivery pipeline не трогать.

---

## Bounded contexts

Не смешивать при reset:

- **Bond Screening** — `domain/bonds`, `domain/screening`
- **Portfolio Planning** — `domain/portfolio/` (pure)
- **Trading** — `domain/trading/` + ports
- **Notifications** — `domain/notifications/` + infrastructure delivery

Notifier vs API — разные entrypoints, **одна** детекция (`collect_alerts`). См. таблицу границ в AGENTS.md.

---

## Тестирование

| Слой | Стратегия reset |
|------|-----------------|
| Domain | Unit на бизнес-сценарии: `tests/unit/domain/` |
| API | `tests/unit/api/` |
| Frontend | E2E бизнес-сценарии: `e2e/playwright/tests/mocked/` |

```bash
# Unit (без сети)
uv run --directory backend pytest tests/unit -m "not sandbox"

# E2E mocked (без API)
cd e2e/playwright && npx playwright test tests/mocked
```

При reset **удаляй** structure-тесты; **оставляй/переписывай** behavior-тесты.

Используй `tests/factories.py` и `conftest.py` — не копируй setup.

P0-покрытие (ориентир): `test_planner.py`, `test_plan_simulation.py`, `test_scorer.py`, `test_trading_advisory.py`, `test_notification_rules.py`.

---

## Project-specific антипаттерны

- Детекция алертов inline в `advise()` или `scan_use_case` вместо `collect_alerts()`
- Бизнес-логика во frontend (только backend; UI — read-model)
- Дублирование pricing на фронте (только `/orders/preview`)
- Shadow-поля плана вместо `advice.holdings` для факта на счёте
- MOEX refresh в hot-path `advise()` (это делает notifier)
- Новый модуль вместо расширения `put_offer.py`, `selection.py`, `deploy_cash.py`

---

## Конвенции рефакторинга (из AGENTS.md)

- **KISS** — минимальный diff
- **DRY** — shared helpers: `factories.py`, `put_offer.py`, `labels.ts`
- **SRP** — один модуль = одна ответственность
- **Low coupling** — domain без infrastructure imports
- **TDD** — Red → Green → Refactor на бизнес-сценариях

Усиливает workspace rules: `.cursor/rules/DRY.mdc`, `.cursor/rules/tdd.mdc`.

---

## Success metrics (дополнение)

Помимо общих метрик из personal skill, для bond-monitor проверь:

- Нет новых нарушений dependency rule (`domain/` → `infrastructure/`)
- Число вызовов `collect_alerts()` / `deploy_cash()` не размножилось
- Frontend diff не содержит бизнес-расчётов
- Net LOC в `domain/` не вырос без обоснования в Diagnosis
