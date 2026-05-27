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
                                                                  │             ui/components.py
                                                                  ▼
                                          core/portfolio_planner.py ──► ui/portfolio.py
                                          core/portfolio_model.py        (вкладка «Портфель»)
                                          data/portfolios.py
                                          data/trading_client.py (stub)
```

Каждый слой независим: можно заменить источник данных, не трогая скоринг или UI.

---

## Ключевые типы

- `BondRecord` (`core/bond_model.py`) — единственная модель данных по облигации. Содержит поля из всех источников. **Добавляй новые поля сюда, а не в промежуточные словари.**
- `CouponType` (enum) — FIXED / FLOATING / VARIABLE / UNKNOWN
- `RiskLevel` (enum) — UNKNOWN(0) / LOW(1) / MODERATE(2) / HIGH(3)
- `Portfolio` / `PortfolioPosition` / `ReinvestmentSlot` (`core/portfolio_model.py`) — типы для модуля «Портфель». Только данные и (де)сериализация в JSON; вся логика — в `core/portfolio_planner.py`.
- `RiskProfile` (enum) — NORMAL / AGGRESSIVE; влияет и на фильтрацию универса, и на веса в `score_bonds_for_profile`.
- `PutOfferDecision` (enum) — PENDING / EXERCISE / HOLD; решение пользователя по ближайшей пут-оферте, сохраняется в позиции.

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

## Портфели

Модуль «Портфель» — отдельная вкладка `tab_portfolio` в `app.py`. Состоит из четырёх слоёв:

| Слой                    | Файл                          | Что делает                                                                                                |
|-------------------------|-------------------------------|-----------------------------------------------------------------------------------------------------------|
| Модель данных           | `core/portfolio_model.py`     | `Portfolio`, `PortfolioPosition`, `ReinvestmentSlot` + перечисления (`RiskProfile`, `PutOfferDecision`)   |
| Персистентность         | `data/portfolios.py`          | `cache/portfolios.json` (envelope `{_updated_at, _count, portfolios: [...]}`) + CRUD (атомарная запись)  |
| Бизнес-логика           | `core/portfolio_planner.py`   | `auto_compose`, `select_replacement`, `build_plan`, `risk_profile_filter`; чистые функции, без Streamlit |
| Скоринг                 | `core/scorer.py`              | `score_bonds_for_profile(...)` с весами под профиль                                                       |
| UI                      | `ui/portfolio.py`             | Селектор портфелей, форма настроек, таблица позиций, слоты реинвестиций, cashflow-таймлайн, заглушка API  |

### Хранение

`cache/portfolios.json` лежит в read-write cache-директории (Docker: `./cache:/app/cache`). Не коммитится в git (исключено `cache/` в `.gitignore`). Структура:

```json
{
  "_updated_at": "...",
  "_count": 1,
  "portfolios": [{
    "id": "<uuid4-hex>",
    "name": "...",
    "initial_amount_rub": 100000.0,
    "horizon_date": "2027-06-01",
    "risk_profile": "normal",
    "cash_balance_rub": 12500.0,
    "positions": [/* PortfolioPosition.to_dict() */],
    "slots":    [/* ReinvestmentSlot.to_dict()    */]
  }]
}
```

### Риск-профили

| Профиль       | Уровень риска T-Invest | Мин. рейтинг | Допуски                                  | Веса скоринга (YTM/Risk/Liq) |
|---------------|------------------------|--------------|------------------------------------------|------------------------------|
| `NORMAL`      | LOW, MODERATE          | `ruA-`       | без субординации, без HIGH-риска         | 0.30 / 0.50 / 0.20           |
| `AGGRESSIVE`  | LOW, MODERATE, HIGH    | `ruBB-`      | разрешены амортизация, колл-оферта, субор. | 0.65 / 0.20 / 0.15           |

Дефолтные/тех.дефолтные эмиссии отсекаются в обоих профилях. Бумаги без кредитного рейтинга в NORMAL отбрасываются (нельзя оценить риск), в AGGRESSIVE — пропускаются.

**«Только для квалов» НЕ отсекаются:** регуляторное ограничение доступа не является свойством риска бумаги. Если у пользователя есть статус квала — он сможет торговать; если нет — брокер просто не пропустит сделку. Решение оставлено пользователю.

### Автосостав — алгоритм диверсификации

`auto_compose` в `core/portfolio_planner.py` строит стартовый набор по принципу «равномерные доли + потолок + минимум»:

| Константа                   | Значение | Смысл                                                                       |
|-----------------------------|----------|-----------------------------------------------------------------------------|
| `TARGET_POSITION_SHARE`     | 0.18     | Целевая доля одной позиции (~5–6 позиций при достаточном бюджете)           |
| `MAX_POSITION_SHARE`        | 0.30     | Жёсткий потолок: не более 30% бюджета в одну бумагу                          |
| `MIN_POSITION_SHARE`        | 0.03     | Минимум для одной позиции — отсекаем огрызки                                 |
| `MIN_POSITION_AMOUNT_RUB`   | 5 000 ₽  | Абсолютный минимум одной позиции (страховка для маленьких бюджетов)         |
| `MIN_AUTO_POSITIONS`        | 4        | Минимум позиций, к которым стремимся (если хватает бюджета)                  |
| `MAX_AUTO_POSITIONS`        | 10       | UX-потолок — больше пользователю тяжело обозревать                            |

Алгоритм:

1. **Первый проход:** идём по топу скоринга, для каждой бумаги покупаем `round(target / lot_cost)` лотов. Дорогие «джамбо»-выпуски (lot > 30% бюджета) пропускаются.
2. **Доразмещение:** оставшийся кэш «дораскидывается» по уже купленным позициям по 1 лоту, начиная с самых прибыльных, до потолка `MAX_POSITION_SHARE`.
3. **Догон до минимума диверсификации:** если позиций < 4, пробуем добавить ещё бумаги из топа.

В результате типичное распределение для бюджета 400 000 ₽ — 5–6 позиций по 15–25%, без позиций меньше 5–12 тыс. ₽.

### Купонная модель (важно для коротких бумаг)

В `core/portfolio_planner._coupon_dates_in_range` купоны якорятся на `PortfolioPosition.next_coupon_date` (берётся из MOEX в момент покупки), а не на `purchase_date + period`. Это критично для коротких бумаг, где первый запланированный купон по простой формуле попадает ЗА дату погашения: в реальности эмитент платит итоговый купон в дату погашения. Якорь по `next_coupon_date` корректно его ловит (последний купон обычно совпадает с `maturity_date`). Для старых позиций без `next_coupon_date` (сохранённых до фикса) — fallback на `purchase_date + period`, плюс попытка подтянуть `next_coupon_date` из live-универса MOEX при перерасчёте плана.

### Реинвестиции

* **Гэп между событием и покупкой замены:** `REINVESTMENT_GAP_DAYS = 2` (T+2 сеттлмент MOEX + день на принятие решения).
* **Окно напоминания о пут-оферте:** `PUT_OFFER_REMINDER_DAYS = 30`. Внутри этого окна позиция в состоянии `PutOfferDecision.PENDING` появляется в блоке напоминаний с двумя кнопками «Предъявить» / «Держать».
* **Купонный кэш:** на каждом шаге `COUPON_CASH_REINVEST_INTERVAL_DAYS = 180` `build_plan` пытается реинвестировать накопленные купоны в новый лот, если набралось достаточно средств.
* **Глубина цепочек:** `MAX_REINVEST_DEPTH = 10`. Цепочка погашение → реинвест → погашение → … обрывается на этой глубине; в плане появляется note.

### Удерживаемые бумаги и итоговые цифры

`PortfolioPlan` хранит две агрегированные «прибыли»:

* `total_net_profit_rub = final_cash_balance - initial_amount` — **реализованная** прибыль: только деньги, которые превратились в кэш к горизонту.
* `total_net_profit_with_held_rub = final_portfolio_value - initial_amount` — прибыль **с учётом** недогашенных бумаг (их оценочная стоимость = `live dirty_price × кол-во` или, если нет цены, `face × кол-во`).

`HeldPositionAtHorizon` (поле `plan.held_positions`) — список позиций, у которых `maturity_date > horizon_date`. Появляются они в одном из случаев: (а) пользователь явно купил бумагу с погашением после горизонта; (б) реинвестиционная цепочка упёрлась в горизонт. В UI отдельным экспандером показывается «что именно ещё не погашено и сколько это стоит».

### Слоты — где живёт пользовательский override

`ReinvestmentSlot.confirmed_isin` — единственная пользовательская мутация в плане, которая переживает rerun. Остальные поля слотов (`trigger_date`, `expected_cash_rub`, `suggested_isin`) пересчитываются `build_plan` каждый раз.

* `suggested_isin` — что предложил планировщик (через `select_replacement`).
* `confirmed_isin` — что выбрал пользователь в UI («Применить выбор»).
* В `Portfolio.slots` upsert-ятся ТОЛЬКО слоты с явным override (`confirmed_isin != None`); чистые auto-suggestion-ы не сохраняются — это уменьшает шум в JSON.

### Валидация бумаги-замены (`validate_replacement_bond`)

Любая бумага, которая должна стать phantom-позицией реинвест-цепочки, проходит через `core.portfolio_planner.validate_replacement_bond(bond, slot_purchase_date, horizon)`. Функция возвращает `None` если всё ок, иначе короткое описание причины. Текущие правила:

1. `bond.maturity_date is not None`
2. `bond.maturity_date > slot_purchase_date` (строго: купить уже погашенную бумагу нельзя)
3. До погашения остаётся не меньше `MIN_REPLACEMENT_HORIZON_DAYS` (30 дн.)
4. `bond.maturity_date ≤ horizon` (бумага должна успеть вернуться в кэш в пределах плана)
5. Нет дефолта / тех.дефолта

**Зачем это нужно (история бага).** В UI-селекте `_render_single_slot` раньше показывались ВСЕ бумаги профильного универса, без фильтра по дате погашения. Можно было «применить выбор» с бумагой, которая гасится ДО даты покупки слота — например, выбрать бумагу с maturity 2026-08-06 для слота с purchase_date 2027-01-22. `build_plan` создавал phantom с `purchase_date = 2027-01-22`, `maturity_date = 2026-08-06`, и эмитил maturity-событие В ПРОШЛОЕ относительно purchase. После сортировки `_event_sort_key` (по дате) cash приходил в августе, а тратился в январе — «деньги из воздуха». Каскад reinvest-цепочек умножал эту иллюзию. Итог — прибыль удваивалась-утраивалась.

После фикса:

* `build_plan` валидирует `target_bond` перед созданием phantom; если невалидно — заносит запись в `plan.notes` и `continue`. Битый `confirmed_isin` автоматически очищается через `_remove_persisted_slot_override` (см. ниже).
* `_maybe_add_coupon_cash_reinvestments` дополнительно валидирует кандидата от `select_replacement` (defensive — на случай несвежего универса).
* В UI `_render_single_slot` список кандидатов в selectbox формируется ТОЛЬКО из тех, что прошли `validate_replacement_bond`. Если кандидатов нет — выводится явный warning. Если у слота `suggested_isin = None` (планировщик не нашёл автозамену) — выводится info-блок.

### Автоматическая очистка битых override (`_remove_persisted_slot_override`)

Если в `cache/portfolios.json` лежит `confirmed_isin`, указывающий на непригодную бумагу (например, после смены даты горизонта портфеля или ухода бумаги из универса MOEX), `build_plan` сам обнулит этот override, удалит «пустой» слот из `portfolio.slots` и сохранит изменения через `update_portfolio`. Пользователь увидит note вида «ваш override отклонён (причина)». Это критично: иначе битый override каждый раз генерировал бы абсурдный cashflow при `st.rerun()`.

### Удаление позиции из таблицы

Таблица позиций (`render_positions_table` в `ui/portfolio.py`) использует `st.column_config.LinkColumn`:

* **«↗»** → ссылка с query-param `?bond=<SECID>` — открывает детальную страницу бумаги (тот же роутинг, что в скринере/избранном).
* **«✕»** → ссылка с query-param `?pos_remove=<ISIN>&portfolio_id=<ID>`. Параметр перехватывается в начале `app.py` (до рендера вкладок), позиция и связанные слоты удаляются через `update_portfolio`, после чего query-params чистятся и происходит `st.rerun`. Так пользователь видит обновлённое состояние сразу.

### Когда менять что

* **Новая стратегия профилей** (например, «защитный»): добавить ветку в `risk_profile_filter` + свой кортеж весов в `_PROFILE_WEIGHTS` (`core/scorer.py`).
* **Корректировка диверсификации:** `TARGET_POSITION_SHARE`, `MAX_POSITION_SHARE`, `MIN_POSITION_SHARE`, `MIN_AUTO_POSITIONS`, `MAX_AUTO_POSITIONS` (`core/portfolio_planner.py`).
* **Новые типы реинвестиции** (например, «купон → депозит»): добавить значение в `ReinvestmentTriggerReason`, обработать в `build_plan` и UI-метках (`_TRIGGER_REASON_LABELS`).
* **Изменение хранения:** `data/portfolios.py` — единственный модуль, знающий путь к `cache/portfolios.json`; UI/планировщик — нет.

---

## Расширение: API торговли

`data/trading_client.py` сейчас содержит только интерфейсный скелет:

* `TradeOrder` (dataclass) — направление BUY/SELL, FIGI, лотность, опциональная лимитная цена.
* `submit_order(order, token)` — бросает `NotImplementedError` сознательно.

UI (`ui/portfolio.render_trading_stub_section`) рендерит disabled-кнопку «Отправить план на биржу», чтобы зафиксировать точку интеграции.

План реализации:

1. Используем `tinkoff-investments` (тот же пакет, что в `data/tinvest_client.py` для read-only обогащения). У него есть `tinkoff.invest.OrdersService.post_order` / `cancel_order` / `get_order_state`.
2. Маппинг: `BondRecord.figi` → `OrderRequest.figi`; направление `BUY` / `SELL` → `ORDER_DIRECTION_BUY` / `ORDER_DIRECTION_SELL`; объём в лотах.
3. Сначала включаем sandbox через `Client(token, sandbox=True)`: виртуальные деньги, тесты без риска (отдельный `SandboxOrdersService`).
4. Production-режим — отдельный токен с правом «торговля» (read-only текущий не подойдёт).
5. Перед отправкой — двойная сверка ISIN/FIGI с локальной позицией портфеля и audit-лог в `cache/orders.log`.

Документация: <https://russianinvestments.github.io/investAPI/sandbox/>, <https://russianinvestments.github.io/investAPI/orders/>.

---

## Тестирование

Юнит-тесты отсутствуют в v0.1, но скоринговые функции специально изолированы для тестируемости:

```python
from core.scorer import calc_risk_score
from core.bond_model import BondRecord, RiskLevel

bond = BondRecord(secid="TEST", isin="RU000TEST", risk_level=RiskLevel.LOW)
assert calc_risk_score(bond) == 80.0
```

Функции планировщика портфеля (`risk_profile_filter`, `auto_compose`, `select_replacement`, `build_plan`) тоже спроектированы как чистые: принимают `today` и `universe` параметрами, не зовут Streamlit, не лезут в файловую систему. Тестируются ровно так же — собрать синтетический список `BondRecord`, передать в функцию, проверить результат.

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

`./cache:/app/cache` смонтирован read-write — там же лежат `ratings_auto.json` (auto-слой рейтингов, пишется кнопкой «Обновить рейтинги»), `favorites.json` (избранные ISIN-ы) и `portfolios.json` (модуль «Портфель»). Все три файла переживают рестарт контейнера.

---

## Расширение стратегии

Для добавления новой стратегии (например, среднесрочные флоатеры или ВДО):
1. Добавь новый набор фильтров/параметров в `app.py` (через `st.selectbox("Стратегия", ...)`)
2. В `core/scorer.py` добавь альтернативный `score_bonds_strategy_xxx()` с другими весами
3. Маршрутизируй по выбранной стратегии в `load_bonds()`
