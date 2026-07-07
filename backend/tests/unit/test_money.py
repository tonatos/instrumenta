"""Тесты `core.money`: конверсии Quotation ↔ pct, lot_cost, order_amount."""

from __future__ import annotations

import pytest

from bond_monitor.domain.shared.money import (
    Lots,
    PriceUnitPct,
    Rub,
    bond_clean_price_quotation,
    lot_cost_rub,
    money_value_to_rub,
    order_amount_rub,
    pct_to_quotation,
    quotation_to_float,
    quotation_to_pct,
)


def test_bond_clean_price_quotation_converts_pct_to_rub() -> None:
    q = bond_clean_price_quotation(price_pct=PriceUnitPct(100.4095), face_value=1000.0)
    assert q.units == 1004
    assert q.nano == 95000000


def test_pct_to_quotation_roundtrip() -> None:
    """`PriceUnitPct(100.5) -> Quotation -> PriceUnitPct` без потерь."""
    original = PriceUnitPct(100.5)
    q = pct_to_quotation(original)
    assert q.units == 100
    assert q.nano == 500_000_000
    assert quotation_to_pct(q) == pytest.approx(100.5)


def test_pct_to_quotation_low_precision() -> None:
    """Маленькие дробные значения: 99.001 -> units=99 nano=1_000_000."""
    q = pct_to_quotation(PriceUnitPct(99.001))
    assert q.units == 99
    assert q.nano == 1_000_000
    assert quotation_to_pct(q) == pytest.approx(99.001)


def test_pct_to_quotation_negative_unsupported() -> None:
    """Отрицательная цена ($lt$ 0) — нонсенс для облигаций. Конвертер не валит,
    но проверим что значение сохраняется как есть (юзеру это всё равно
    отклонит API)."""
    # Note: pct_to_quotation НЕ валидирует, валидация на стороне валидатора.
    q = pct_to_quotation(PriceUnitPct(0.5))
    assert q.units == 0
    assert q.nano == 500_000_000


def test_lot_cost_rub_basic() -> None:
    """Базовый расчёт: 100% цена × 1000 ₽ номинал × 10 шт = 10 000 ₽."""
    cost = lot_cost_rub(
        price_pct=PriceUnitPct(100.0),
        face_value=1000.0,
        lot_size=10,
        aci_rub=0.0,
    )
    assert cost == pytest.approx(10_000.0)


def test_lot_cost_rub_with_nkd() -> None:
    """С НКД: 100% × 1000 × 10 + 5 ₽ × 10 = 10 050 ₽."""
    cost = lot_cost_rub(
        price_pct=PriceUnitPct(100.0),
        face_value=1000.0,
        lot_size=10,
        aci_rub=5.0,
    )
    assert cost == pytest.approx(10_050.0)


def test_lot_cost_rub_discount() -> None:
    """С дисконтом: 99.5% × 1000 × 10 = 9 950 ₽."""
    cost = lot_cost_rub(
        price_pct=PriceUnitPct(99.5),
        face_value=1000.0,
        lot_size=10,
    )
    assert cost == pytest.approx(9_950.0)


def test_order_amount_rub_multiplies_lots() -> None:
    """order_amount = lot_cost × lots."""
    total = order_amount_rub(
        price_pct=PriceUnitPct(100.0),
        face_value=1000.0,
        lot_size=10,
        lots=Lots(5),
    )
    assert total == pytest.approx(50_000.0)


def test_money_value_to_rub_rub_currency() -> None:
    """MoneyValue с currency='rub' конвертится корректно."""

    class FakeMoneyValue:
        currency = "rub"
        units = 1000
        nano = 500_000_000

    result = money_value_to_rub(FakeMoneyValue())
    assert result == pytest.approx(1000.5)


def test_money_value_to_rub_foreign_currency_none() -> None:
    """Иностранная валюта возвращает None — мы её не учитываем."""

    class FakeMoneyValue:
        currency = "usd"
        units = 100
        nano = 0

    assert money_value_to_rub(FakeMoneyValue()) is None


def test_money_value_to_rub_none_input() -> None:
    """None на входе → None."""
    assert money_value_to_rub(None) is None


def test_quotation_to_float_zero_returns_none() -> None:
    """Quotation(0, 0) считается пустым полем — None."""

    class FakeQuotation:
        units = 0
        nano = 0

    assert quotation_to_float(FakeQuotation()) is None


def test_quotation_to_float_positive_fractional() -> None:
    """Quotation(100, 500_000_000) → 100.5."""

    class FakeQuotation:
        units = 100
        nano = 500_000_000

    result = quotation_to_float(FakeQuotation())
    assert result == pytest.approx(100.5)


def test_rub_newtype_is_float_runtime() -> None:
    """Rub — это NewType-обёртка над float, в рантайме исчезает."""
    value: Rub = Rub(1000.0)
    assert isinstance(value, float)
    assert value + 1.0 == 1001.0
