"""
Скелет интерфейса для биржевой торговли через API.

Этот модуль — заведомо заглушка. Реальный submit пока не реализован
сознательно: торговля требует продакшн-токена с правом записи и
дополнительной обвязки (sandbox-режим, риск-лимиты, логирование сделок,
audit-trail). Здесь определены только типы и контракт, чтобы UI и
портфельный планировщик могли ссылаться на них без условных импортов.

План интеграции (когда дойдём):

1. Использовать `tinkoff-investments` (тот же пакет, что уже подключен в
   :mod:`data.tinvest_client` для read-only обогащения). У него есть
   :class:`tinkoff.invest.OrdersService` с методами
   ``post_order`` / ``cancel_order`` / ``get_order_state``.
2. Маппинг ``BondRecord.figi`` → ``OrderRequest.figi``; направления
   ``BUY`` / ``SELL`` соответствуют ``ORDER_DIRECTION_BUY`` /
   ``ORDER_DIRECTION_SELL``; объём — в лотах.
3. Сначала включаем sandbox через ``Client(token, sandbox=True)``: там
   деньги виртуальные, можно тестировать без риска. Sandbox также имеет
   отдельный сервис ``SandboxOrdersService``.
4. Production-режим — отдельный токен с разрешением «торговля»
   (read-only токен, который сейчас используется для котировок,
   `OrdersService` отклонит).
5. Перед отправкой обязательно валидировать соответствие FIGI/тикера
   позиции в портфеле — чтобы не купить случайно не ту бумагу из-за
   опечатки в ISIN.

См. также:
    * Sandbox guide: https://russianinvestments.github.io/investAPI/sandbox/
    * Orders service:
      https://russianinvestments.github.io/investAPI/orders/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NoReturn

OrderDirection = Literal["BUY", "SELL"]


@dataclass
class TradeOrder:
    """Описание заявки на покупку/продажу облигации.

    Поля выровнены под T-Invest ``PostOrderRequest`` (см. план интеграции
    в module-docstring), но не зависят от конкретного SDK — это позволяет
    в будущем подменить транспорт без правок UI/планировщика.

    Args:
        direction: ``"BUY"`` (покупка) или ``"SELL"`` (продажа).
        figi: Глобальный идентификатор инструмента (берём из
            :attr:`core.bond_model.BondRecord.figi`).
        lots: Количество лотов (не облигаций). 1 лот = ``lot_size`` облигаций.
        price_rub: Лимитная цена покупки в рублях за облигацию; ``None`` →
            рыночная заявка.
    """

    direction: OrderDirection
    figi: str
    lots: int
    price_rub: float | None = None


def submit_order(order: TradeOrder, token: str) -> NoReturn:
    """Отправить заявку на биржу. **Не реализовано в v1.**

    Бросает :class:`NotImplementedError`. Не вызывайте из боевого кода —
    UI лишь показывает кнопку-заглушку, чтобы зафиксировать API-точку
    интеграции.

    Когда дойдут руки до реализации:

    * Добавить пакет ``tinkoff-investments`` (он уже есть как опциональная
      зависимость для :mod:`data.tinvest_client`).
    * Завернуть вызов в try/except для разделения сетевых ошибок,
      ошибок валидации и отказов биржи.
    * Логировать каждый успешный submit в audit-журнал
      (например, ``cache/orders.log``).
    """
    raise NotImplementedError(
        "Live trading is intentionally not implemented in v1; "
        "see data.trading_client docstring and AGENTS.md → "
        "«Расширение: API торговли» for the integration plan."
    )
