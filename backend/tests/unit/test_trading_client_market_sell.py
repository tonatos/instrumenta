"""Unit tests for post_market_sell_order — must use LIMIT, not BESTPRICE."""

from __future__ import annotations

from unittest.mock import patch

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import (
    PostOrderResult,
    post_market_sell_order,
)


def test_post_market_sell_order_delegates_to_limit_with_discount() -> None:
    with patch(
        "bond_monitor.infrastructure.tinvest.trading_client.post_limit_order",
        return_value=PostOrderResult(
            order_id="ord-1",
            request_uid="uid-1",
            execution_report_status="EXECUTION_REPORT_STATUS_FILL",
            lots_executed=2,
            lots_requested=2,
            executed_price_pct=PriceUnitPct(92.0),
            initial_order_price_rub=None,
            total_order_amount_rub=Rub(18_400.0),
            initial_commission_rub=None,
        ),
    ) as limit_mock:
        result = post_market_sell_order(
            "token",
            AccountKind.SANDBOX,
            account_id="acc-1",
            instrument_id="uid-bond",
            lots=Lots(2),
            request_uid="uid-1",
            reference_price_pct=PriceUnitPct(100.0),
            lot_size=10,
        )

    assert result.order_id == "ord-1"
    limit_mock.assert_called_once()
    kwargs = limit_mock.call_args.kwargs
    assert kwargs["figi"] == ""
    assert kwargs["instrument_uid"] == "uid-bond"
    assert kwargs["direction"] == "SELL"
    assert float(kwargs["price_pct"]) == 97.0  # 3% discount from 100%
