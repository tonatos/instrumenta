"""Tests for ensure_order_instrument preflight checks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bond_monitor.infrastructure.tinvest.read_client import (
    TradeAvailability,
    ensure_order_instrument,
)
from bond_monitor.infrastructure.tinvest.trading_client import TradingNotAvailableError


def test_ensure_order_instrument_rejects_api_forbidden() -> None:
    trade = TradeAvailability(
        api_trade_available_flag=False,
        buy_available_flag=True,
        sell_available_flag=True,
        figi="BBG123",
        instrument_uid="uid-1",
        lot_size=1,
    )

    with (
        patch(
            "bond_monitor.infrastructure.tinvest.read_client.check_trade_available",
            return_value=trade,
        ),
        pytest.raises(TradingNotAvailableError, match="api_trade_available_flag"),
    ):
        ensure_order_instrument("token", figi="BBG123", isin="RU000ATEST", direction="BUY")


def test_ensure_order_instrument_returns_trade_when_available() -> None:
    trade = TradeAvailability(
        api_trade_available_flag=True,
        buy_available_flag=True,
        sell_available_flag=True,
        figi="BBG123",
        instrument_uid="uid-1",
        lot_size=1,
    )

    with patch(
        "bond_monitor.infrastructure.tinvest.read_client.check_trade_available",
        return_value=trade,
    ):
        result = ensure_order_instrument("token", figi="BBG123", direction="BUY")

    assert result.instrument_uid == "uid-1"
