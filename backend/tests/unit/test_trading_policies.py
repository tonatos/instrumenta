"""Тесты буфера лимитной цены покупки."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.trading.policies import (
    BUY_LIMIT_PRICE_BUFFER_PRODUCTION,
    BUY_LIMIT_PRICE_BUFFER_SANDBOX,
    buy_limit_price_buffer,
    format_buy_limit_buffer_label,
    suggested_buy_limit_price_pct,
)


def test_buy_limit_price_buffer_by_account_kind() -> None:
    assert buy_limit_price_buffer(AccountKind.SANDBOX) == BUY_LIMIT_PRICE_BUFFER_SANDBOX
    assert buy_limit_price_buffer(AccountKind.PRODUCTION) == BUY_LIMIT_PRICE_BUFFER_PRODUCTION
    assert buy_limit_price_buffer(None) == BUY_LIMIT_PRICE_BUFFER_SANDBOX


def test_format_buy_limit_buffer_label() -> None:
    assert format_buy_limit_buffer_label(BUY_LIMIT_PRICE_BUFFER_SANDBOX) == "0.5%"
    assert format_buy_limit_buffer_label(BUY_LIMIT_PRICE_BUFFER_PRODUCTION) == "0.2%"


def test_suggested_buy_limit_price_pct() -> None:
    assert float(suggested_buy_limit_price_pct(100.0, BUY_LIMIT_PRICE_BUFFER_SANDBOX)) == 100.5
    assert float(suggested_buy_limit_price_pct(100.0, BUY_LIMIT_PRICE_BUFFER_PRODUCTION)) == 100.2
