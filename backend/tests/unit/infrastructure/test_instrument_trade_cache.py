"""Tests for instrument trade availability cache during trading sync."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from bond_monitor.application.trading.order_use_case import block_non_api_tradable_pending
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
    PendingOperation,
)
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    TradingNotAvailableError,
)


def _portfolio() -> Portfolio:
    return Portfolio(
        name="Cache Test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )


def _snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(100_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def test_block_non_api_tradable_pending_uses_cached_tradable_result() -> None:
    portfolio = _portfolio()
    portfolio.instrument_trade_cache["RU000ATEST:BUY"] = {
        "api_tradable": True,
        "figi": "FIGI-CACHED",
        "block_reason": None,
    }
    pending = [
        PendingOperation(
            kind="initial_buy",
            isin="RU000ATEST",
            name="Test Bond",
            lots=1,
            suggested_price_pct=100.0,
        )
    ]

    with patch(
        "bond_monitor.application.trading.broker.ensure_order_instrument",
    ) as ensure_mock:
        block_non_api_tradable_pending(portfolio, "token", pending, _snapshot())

    ensure_mock.assert_not_called()
    assert pending[0].figi == "FIGI-CACHED"
    assert pending[0].status == "action_required"


def test_block_non_api_tradable_pending_uses_cached_blocked_result() -> None:
    portfolio = _portfolio()
    portfolio.instrument_trade_cache["RU000ATEST:BUY"] = {
        "api_tradable": False,
        "figi": None,
        "block_reason": "blocked by cache",
    }
    pending = [
        PendingOperation(
            kind="initial_buy",
            isin="RU000ATEST",
            name="Test Bond",
            lots=1,
            suggested_price_pct=100.0,
        )
    ]

    with patch(
        "bond_monitor.application.trading.broker.ensure_order_instrument",
    ) as ensure_mock:
        block_non_api_tradable_pending(portfolio, "token", pending, _snapshot())

    ensure_mock.assert_not_called()
    assert pending[0].status == "blocked"
    assert pending[0].block_reason == "blocked by cache"


def test_block_non_api_tradable_pending_stores_api_result_in_cache() -> None:
    portfolio = _portfolio()
    pending = [
        PendingOperation(
            kind="initial_buy",
            isin="RU000ATEST",
            name="Test Bond",
            lots=1,
            suggested_price_pct=100.0,
        )
    ]

    with patch(
        "bond_monitor.application.trading.broker.ensure_order_instrument",
        side_effect=TradingNotAvailableError("not tradable"),
    ):
        block_non_api_tradable_pending(portfolio, "token", pending, _snapshot())

    assert portfolio.instrument_trade_cache["RU000ATEST:BUY"]["api_tradable"] is False
    assert pending[0].status == "blocked"
