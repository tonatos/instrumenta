"""
Строгие денежные/количественные типы для домена режима торговли.

Облигации торгуются в **процентах от номинала** (например, цена ``100.5%``
означает ``1005 ₽`` при номинале ``1000 ₽``), а лимитные заявки в API
T-Invest принимают цену как `Quotation` (units + nano) — структуру с
фиксированной точкой. Между этими тремя представлениями лёгкая каша
(`float` рубли vs `float` проценты vs `Quotation`) — частый источник
ошибок «купил/продал не туда».

Здесь определены `NewType`-обёртки, маркирующие смысл значения, и
явные конвертеры. Применяются агрессивно во всех новых модулях
(`trading_client`, `pending_operations`, `yield_calc`, `portfolio_reconciler`).
В существующих симуляционных модулях — точечно, по местам соприкосновения
с торговым слоем, без сплошного рефакторинга.

Примечание:
    `NewType` — лёгкая аннотация для статического анализа (`mypy`,
    `pyright`), в рантайме `Rub(1000.0)` это просто `float`. Это
    сознательный компромисс: мы хотим ловить ошибки в IDE/CI, но не
    платить за value-объекты.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, NewType

if TYPE_CHECKING:
    # Импортируем Quotation только для type-hints, чтобы основной импорт
    # `core.money` не требовал `t_tech.invest` (модуль чистый, должен
    # импортироваться в тестах без внешних зависимостей).
    from t_tech.invest import Quotation


# Сумма в российских рублях, включая копейки. Положительная — приход,
# отрицательная — расход (как в `CashflowEvent.amount_rub`).
Rub = NewType("Rub", float)


# Цена облигации в процентах от номинала. ``100.0`` = по номиналу,
# ``99.5`` = с дисконтом, ``101.5`` = с премией. Используется в MOEX
# (`last_price`), в `BondRecord.last_price`, в `PortfolioPosition.purchase_clean_price_pct`,
# и в полях `price_pct` всех новых dataclass-ов trading-слоя.
PriceUnitPct = NewType("PriceUnitPct", float)


# Количество лотов. 1 лот = ``lot_size`` облигаций (от 1 до 100+).
Lots = NewType("Lots", int)


# Хард-лимит T-Invest API на сумму одной заявки. Заявки сверх лимита
# требуют SMS-подтверждения, которое через API не доступно (см.
# AGENTS.md «Режим торговли»). Все суммы в ``data.trading_client``
# проверяются на этот порог ДО `post_order`.
MAX_ORDER_AMOUNT_RUB: Rub = Rub(30_000_000.0)


def lot_cost_rub(
    *,
    price_pct: PriceUnitPct,
    face_value: float,
    lot_size: int,
    aci_rub: float = 0.0,
) -> Rub:
    """Стоимость одного лота облигации в рублях (грязная цена).

    Args:
        price_pct: Цена в % от номинала (например, ``100.5``).
        face_value: Номинал одной облигации в ₽ (``1000.0`` по умолчанию
            для большинства корпоративных бумаг).
        lot_size: Количество облигаций в одном лоте.
        aci_rub: НКД на одну облигацию в ₽ (если уже учтён в price_pct —
            передавать ``0.0``).

    Returns:
        Грязная цена одного лота в ₽, как ``Rub``.
    """
    clean_per_bond = price_pct / 100.0 * face_value
    dirty_per_bond = clean_per_bond + aci_rub
    return Rub(dirty_per_bond * lot_size)


def order_amount_rub(
    *,
    price_pct: PriceUnitPct,
    face_value: float,
    lot_size: int,
    lots: Lots,
    aci_rub: float = 0.0,
) -> Rub:
    """Общая стоимость заявки (lots × lot × dirty)."""
    return Rub(
        lot_cost_rub(
            price_pct=price_pct,
            face_value=face_value,
            lot_size=lot_size,
            aci_rub=aci_rub,
        )
        * lots
    )


def pct_to_quotation(price_pct: PriceUnitPct) -> Quotation:
    """Сконвертировать числовое значение в proto `Quotation` (units, nano).

    Нормализация до 9 знаков после запятой (формат `Quotation.nano`).
    """
    from t_tech.invest.utils import decimal_to_quotation

    quantized = Decimal(str(price_pct)).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
    return decimal_to_quotation(quantized)


def bond_clean_price_quotation(*, price_pct: PriceUnitPct, face_value: float) -> Quotation:
    """Чистая цена одной облигации в ₽ для `PostOrder` / `GetOrderPrice`.

    В котировках MOEX и в UI цена хранится как % от номинала, а T-Invest API
    для лимитных заявок по облигациям принимает **рублёвую чистую цену за 1 бумагу**.
    """
    clean_per_bond = float(price_pct) / 100.0 * face_value
    return pct_to_quotation(PriceUnitPct(clean_per_bond))


def quotation_to_pct(q: Quotation) -> PriceUnitPct:
    """Обратная конвертация `Quotation` → ``% от номинала`` (как ``float``)."""
    from t_tech.invest.utils import quotation_to_decimal

    return PriceUnitPct(float(quotation_to_decimal(q)))


def money_value_to_rub(mv: object) -> Rub | None:
    """Сконвертировать proto `MoneyValue` в `Rub`.

    Принимает `MoneyValue` (через duck-typing: атрибуты ``units``, ``nano``,
    ``currency``). Возвращает ``None`` для нулевых значений или валют
    отличных от RUB (всё, что не RUB, в портфельной модели не учитывается —
    привязка только к RUB-счёту, см. AGENTS.md).
    """
    if mv is None:
        return None
    currency = getattr(mv, "currency", "").lower()
    if currency and currency != "rub":
        return None
    units = int(getattr(mv, "units", 0))
    nano = int(getattr(mv, "nano", 0))
    return Rub(float(units) + nano / 1_000_000_000.0)


def quotation_to_float(q: object) -> float | None:
    """Сконвертировать proto `Quotation` в обычный `float` (с дробной частью).

    Возвращает ``None`` если ``q`` пустой / нулевой по обеим компонентам
    (для опциональных полей API). Дробная часть `nano` — 9 знаков.
    """
    if q is None:
        return None
    units = int(getattr(q, "units", 0))
    nano = int(getattr(q, "nano", 0))
    if units == 0 and nano == 0:
        return None
    return float(units) + nano / 1_000_000_000.0
