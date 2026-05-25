# AGENTS.md — Гайд по проекту bond-monitor для AI-агентов

Этот файл описывает архитектуру, конвенции и точки расширения проекта.
Читай этот файл перед любыми изменениями кода.

---

## Архитектура (слои)

```
MOEX ISS API          ──► data/moex_client.py     ──┐
T-Invest API          ──► data/tinvest_client.py  ──┤
data/ratings.json (vendored) ─┐                      ├──► core/bond_model.py (BondRecord)
smart-lab.ru/q/bonds/ ──► data/ratings_scraper.py    │           │
                              └──► data/ratings_loader.py ───────┘
                                                                  ▼
                                                          core/scorer.py  ──► app.py (Streamlit)
                                                                                ui/components.py
```

Каждый слой независим: можно заменить источник данных, не трогая скоринг или UI.

---

## Ключевые типы

- `BondRecord` (`core/bond_model.py`) — единственная модель данных. Содержит поля из всех источников. **Добавляй новые поля сюда, а не в промежуточные словари.**
- `CouponType` (enum) — FIXED / FLOATING / VARIABLE / UNKNOWN
- `RiskLevel` (enum) — UNKNOWN(0) / LOW(1) / MODERATE(2) / HIGH(3)

---

## Добавление нового источника данных

1. Создай `data/<source>_client.py` с функцией `enrich_bonds_from_<source>(bonds: list[BondRecord], ...) -> list[BondRecord]`.
2. Добавь нужные поля в `BondRecord` (и `RATING_ORDER` если нужна новая шкала).
3. Вызови функцию в `app.py` внутри `load_bonds()` после основного обогащения.
4. Обнови `requirements.txt` и `Dockerfile`.

---

## Изменение скоринговой модели

Все веса и константы в `core/scorer.py`:
- `KEY_RATE_DEFAULT`, `TAX_RATE_DEFAULT` — дефолты для безрисковой ставки и НДФЛ; реальные значения берутся из env (`KEY_RATE`, `TAX_RATE`) либо из сайдбара
- `_RISK_BASE` — базовые баллы за уровень риска
- `_RATING_BONUSES` — бонусы/штрафы от рейтинга
- Функции `calc_ytm_score`, `calc_risk_score`, `calc_liquidity_score` — изолированы, каждая тестируема отдельно
- Веса (40/40/20) в функции `score_bonds()` — в строке `bond.score = ytm_score * 0.40 + ...`
- **`bond.ytm_net` рассчитывается внутри `score_bonds(..., tax_rate=...)`** на основе текущей ставки НДФЛ; `data/moex_client.py` его НЕ заполняет

---

## Добавление новой вкладки в UI

1. Добавь блок `with tab_new:` в `app.py`.
2. Вспомогательные компоненты (функции `render_*`) помещай в `ui/components.py`.
3. `ui/components.py` не должен иметь логики получения данных — только рендеринг.

---

## Конвенции кода

- Python 3.12+, type hints везде (включая локальные переменные где неочевидно)
- Форматирование: ruff format (line-length = 100, double quotes)
- Линтинг: ruff lint (E + F + I + UP + B + SIM + N)
- Логирование: только через `logging`, без `print()`
- Константы: UPPER_CASE в модульном скоупе
- Нет magic numbers — используй именованные константы
- Docstrings: у всех публичных функций и модулей

Перед коммитом:
```bash
ruff check . --fix
ruff format .
```

---

## Переменные окружения

| Имя | Тип | Описание |
|-----|-----|----------|
| `TINKOFF_TOKEN` | str | T-Invest API токен (read-only); обогащение опционально |
| `KEY_RATE` | float | Ключевая ставка ЦБ, % |
| `TAX_RATE` | float | Ставка НДФЛ, % (внутри кода — доля); применяется к YTM/купонам/приросту |
| `MAX_DAYS` | int | Макс. дней до погашения в скринере |
| `MIN_VOLUME_RUB` | float | Мин. ликвидность в ₽/день |

Все переменные имеют разумные defaults в `app.py` и `core/scorer.py`.

---

## Рейтинги — два слоя

Конвейер рейтингов состоит из двух слоёв, мерджащихся в `data/ratings_loader.apply_ratings`:

### Слой 1: vendored seed (`data/ratings.json`)

Файл лежит в репо, редактируется руками, в Docker монтируется read-only.

- `isin_ratings`: `{"ISIN": "ruXXX"}` — точный матч по ISIN
- `name_ratings`: `{"substring": "ruXXX"}` — поиск подстроки в MOEX SHORTNAME (case-insensitive)

Используется как **fallback** для ОФЗ (там `"ОФЗ": "ruAAA"` и т.п.) и менее ликвидных бумаг, которых нет в авто-источнике.

### Слой 2: auto cache (`cache/ratings_auto.json`)

Авто-обновляемый файл, пишется приложением через кнопку «Обновить рейтинги» в сайдбаре. Не коммитится в git (исключён в `.gitignore`).

- Источник: `https://smart-lab.ru/q/bonds/` — публичная страница, статический HTML с встроенным JS-объектом `var aBondsChartData = {wc: [...]}`. Парсится `data/ratings_scraper.fetch_smartlab_bond_ratings` через `httpx` + `json.JSONDecoder().raw_decode` (без HTML-парсера).
- Покрытие: ~100 самых ликвидных корпоративных облигаций MOEX, точная привязка по ISIN.
- Envelope: `{"_source", "_updated_at", "_count", "isin_ratings": {ISIN: rating}}`.

### Приоритет матчинга

1. **Auto-слой ISIN-match** (точный, на конкретный выпуск)
2. **Vendored ISIN-match** (ручные оверрайды)
3. **Vendored name-substring-match** (бренд-уровень: ОФЗ → ruAAA и т.д.)

### Шкала рейтингов

`ruAAA > ruAA+ > ruAA > ruAA- > ruA+ > ruA > ruA- > ruBBB+ > ... > ruD`

Маппинг в `RATING_ORDER` (`core/bond_model.py`) — числовые ординалы для скоринга. Поддерживается обе формы записи: `ruAAA` (vendored) и `AAA` (smart-lab отдаёт без префикса), числовой ординал одинаковый.

### Когда менять что

- Добавить новый источник авто-рейтингов → создать `data/<source>_scraper.py` по аналогии с `ratings_scraper.py`, дополнить `apply_ratings` новым слоем.
- Исправить рейтинг конкретной бумаги (override) → добавить запись в `isin_ratings` в `data/ratings.json` — слой 2 имеет приоритет, поэтому для оверрайда нужно либо чистить кэш, либо менять `ratings.json` + сбрасывать кэш кнопкой «Обновить рейтинги».
- Расширить fallback для целого бренда → добавить запись в `name_ratings` в `data/ratings.json`.

---

## Тестирование

Юнит-тесты отсутствуют в v0.1, но скоринговые функции специально изолированы для тестируемости:

```python
from core.scorer import calc_risk_score
from core.bond_model import BondRecord, RiskLevel

bond = BondRecord(secid="TEST", isin="RU000TEST", risk_level=RiskLevel.LOW)
assert calc_risk_score(bond) == 80.0
```

Добавляй тесты в `tests/` при разработке новых фич.

---

## Docker

```bash
# Сборка и запуск
docker compose up --build

# Только пересборка без запуска
docker compose build

# Просмотр логов
docker compose logs -f bond-monitor

# Остановка
docker compose down
```

`ratings.json` монтируется в контейнер как read-only volume — изменения на хосте подхватываются после нажатия «Обновить данные» в UI (сбрасывает кэш Streamlit).

`./cache:/app/cache` смонтирован read-write — там же лежит и `ratings_auto.json` (auto-слой рейтингов), который пишется приложением через кнопку «Обновить рейтинги».

---

## Расширение стратегии

Для добавления новой стратегии (например, среднесрочные флоатеры или ВДО):
1. Добавь новый набор фильтров/параметров в `app.py` (через `st.selectbox("Стратегия", ...)`)
2. В `core/scorer.py` добавь альтернативный `score_bonds_strategy_xxx()` с другими весами
3. Маршрутизируй по выбранной стратегии в `load_bonds()`
