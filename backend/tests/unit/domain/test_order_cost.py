"""
Тесты `data.trading_client.post_limit_order` на защиту от чрезмерных заявок.

Юнит-тесты не дёргают T-Invest API: проверяется только защитный layer
(`OrderTooLargeError`) до `post_order`. Реальная отправка тестируется
в `tests/e2e/test_sandbox_happy_path.py`.
"""

from __future__ import annotations

import pytest

from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.shared.money import MAX_ORDER_AMOUNT_RUB, Lots, PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import OrderTooLargeError, post_limit_order


def test_post_limit_order_rejects_oversize() -> None:
    """Заявка > 30 000 000 ₽ должна быть отклонена ДО запроса в API."""
    too_big = Rub(MAX_ORDER_AMOUNT_RUB + 1.0)
    with pytest.raises(OrderTooLargeError):
        post_limit_order(
            "dummy_token",
            AccountKind.SANDBOX,
            account_id="acc",
            figi="BBG000000",
            direction="BUY",
            lots=Lots(1),
            price_pct=PriceUnitPct(100.0),
            face_value=1000.0,
            request_uid="uid-1",
            estimated_total_amount_rub=too_big,
        )


def test_post_limit_order_exactly_at_limit_passes_to_api() -> None:
    """Заявка ровно на лимит проходит preflight (упадёт уже на API на dummy токене)."""
    # Поскольку реального токена нет, ожидаем сетевую/валидационную ошибку,
    # но НЕ OrderTooLargeError.
    exact = Rub(MAX_ORDER_AMOUNT_RUB)
    with pytest.raises(Exception) as exc_info:
        post_limit_order(
            "dummy_token",
            AccountKind.SANDBOX,
            account_id="acc",
            figi="BBG000000",
            direction="BUY",
            lots=Lots(1),
            price_pct=PriceUnitPct(100.0),
            face_value=1000.0,
            request_uid="uid-1",
            estimated_total_amount_rub=exact,
        )
    assert not isinstance(exc_info.value, OrderTooLargeError)


def test_post_limit_order_no_estimate_skips_preflight() -> None:
    """Если `estimated_total_amount_rub=None`, проверка лимита пропускается
    (полагается на ответ API)."""
    with pytest.raises(Exception) as exc_info:
        post_limit_order(
            "dummy_token",
            AccountKind.SANDBOX,
            account_id="acc",
            figi="BBG000000",
            direction="BUY",
            lots=Lots(1),
            price_pct=PriceUnitPct(100.0),
            face_value=1000.0,
            request_uid="uid-1",
        )
    assert not isinstance(exc_info.value, OrderTooLargeError)
