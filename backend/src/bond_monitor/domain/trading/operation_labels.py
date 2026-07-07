"""Human-readable labels for T-Invest operation types and states."""

from __future__ import annotations

_OPERATION_TYPE_LABELS: dict[str, str] = {
    "OPERATION_TYPE_INPUT": "Пополнение",
    "OPERATION_TYPE_OUTPUT": "Вывод",
    "OPERATION_TYPE_BUY": "Покупка",
    "OPERATION_TYPE_BUY_CARD": "Покупка",
    "OPERATION_TYPE_BUY_MARGIN": "Покупка",
    "OPERATION_TYPE_SELL": "Продажа",
    "OPERATION_TYPE_SELL_CARD": "Продажа",
    "OPERATION_TYPE_SELL_MARGIN": "Продажа",
    "OPERATION_TYPE_COUPON": "Купон",
    "OPERATION_TYPE_BOND_REPAYMENT": "Погашение",
    "OPERATION_TYPE_BOND_REPAYMENT_FULL": "Погашение",
    "OPERATION_TYPE_DIVIDEND": "Дивиденд",
    "OPERATION_TYPE_DIV_EXT": "Дивиденд",
    "OPERATION_TYPE_BROKER_FEE": "Комиссия брокера",
    "OPERATION_TYPE_SERVICE_FEE": "Сервисная комиссия",
    "OPERATION_TYPE_OTHER_FEE": "Комиссия",
    "OPERATION_TYPE_TAX": "Налог",
    "OPERATION_TYPE_TAX_PROGRESSIVE": "Налог",
    "OPERATION_TYPE_BOND_TAX": "Налог по облигации",
    "OPERATION_TYPE_BOND_TAX_PROGRESSIVE": "Налог по облигации",
    "OPERATION_TYPE_TAX_CORRECTION": "Корректировка налога",
    "OPERATION_TYPE_TAX_CORRECTION_COUPON": "Корректировка налога",
    "OPERATION_TYPE_DIVIDEND_TAX": "Налог на дивиденды",
    "OPERATION_TYPE_DIVIDEND_TAX_PROGRESSIVE": "Налог на дивиденды",
    "OPERATION_TYPE_ACCRUING_VARMARGIN": "Вариационная маржа",
    "OPERATION_TYPE_WRITING_OFF_VARMARGIN": "Вариационная маржа",
    "OPERATION_TYPE_OVERNIGHT": "Овернайт",
    "OPERATION_TYPE_OVER_COM": "Овернайт",
    "OPERATION_TYPE_OUT_FEE": "Комиссия за вывод",
    "OPERATION_TYPE_OUT_STAMP_DUTY": "Гербовый сбор",
    "OPERATION_TYPE_TRACK_MFEE": "Комиссия за управление",
    "OPERATION_TYPE_TRACK_PFEE": "Комиссия за успех",
    "OPERATION_TYPE_INPUT_SWIFT": "Пополнение SWIFT",
    "OPERATION_TYPE_OUTPUT_SWIFT": "Вывод SWIFT",
    "OPERATION_TYPE_DIVIDEND_TRANSFER": "Перевод дивидендов",
    "OPERATION_TYPE_MARGIN_FEE": "Маржинальная комиссия",
    "OPERATION_TYPE_BENEFIT_TAX": "Налог на льготу",
    "OPERATION_TYPE_BENEFIT_TAX_PROGRESSIVE": "Налог на льготу",
    "OPERATION_TYPE_SECURITY_TRANSFER": "Перевод бумаг",
    "OPERATION_TYPE_DELIVERY_BUY": "Поставка (покупка)",
    "OPERATION_TYPE_DELIVERY_SELL": "Поставка (продажа)",
}

_OPERATION_STATE_LABELS: dict[str, str] = {
    "OPERATION_STATE_EXECUTED": "Исполнена",
    "OPERATION_STATE_CANCELED": "Отменена",
    "OPERATION_STATE_PROGRESS": "В обработке",
}


def operation_type_label(operation_type: str) -> str:
    """Map ``OPERATION_TYPE_*`` to a short Russian label."""
    if operation_type in _OPERATION_TYPE_LABELS:
        return _OPERATION_TYPE_LABELS[operation_type]
    if operation_type.startswith("OPERATION_TYPE_"):
        return operation_type.removeprefix("OPERATION_TYPE_").replace("_", " ").title()
    return operation_type


def operation_state_label(state: str) -> str:
    """Map ``OPERATION_STATE_*`` to a short Russian label."""
    if state in _OPERATION_STATE_LABELS:
        return _OPERATION_STATE_LABELS[state]
    if state.startswith("OPERATION_STATE_"):
        return state.removeprefix("OPERATION_STATE_").replace("_", " ").title()
    return state
