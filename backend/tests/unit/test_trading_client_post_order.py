"""Tests for unified orders.post_order in trading_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import Lots, PriceUnitPct
from bond_monitor.infrastructure.tinvest.trading_client import (
    TradingNotAvailableError,
    post_limit_order,
)


def _mock_order_response() -> MagicMock:
    response = MagicMock()
    response.order_id = "exchange-order-1"
    response.execution_report_status = MagicMock(name="EXECUTION_REPORT_STATUS_NEW")
    response.execution_report_status.name = "EXECUTION_REPORT_STATUS_NEW"
    response.lots_executed = 0
    response.lots_requested = 1
    response.executed_order_price = None
    response.initial_order_price = None
    response.total_order_amount = None
    response.initial_commission = None
    response.message = ""
    return response


def test_post_limit_order_uses_orders_service_for_sandbox() -> None:
    mock_client = MagicMock()
    mock_client.orders.post_order.return_value = _mock_order_response()

    with patch(
        "bond_monitor.infrastructure.tinvest.trading_client._open_client"
    ) as open_client:
        open_client.return_value.__enter__.return_value = mock_client
        result = post_limit_order(
            "token",
            AccountKind.SANDBOX,
            account_id="acc-1",
            figi="BBG123",
            instrument_uid="uid-bond",
            direction="BUY",
            lots=Lots(1),
            price_pct=PriceUnitPct(100.4095),
            face_value=1000.0,
            request_uid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )

    assert result.order_id == "exchange-order-1"
    kwargs = mock_client.orders.post_order.call_args.kwargs
    assert kwargs["instrument_id"] == "uid-bond"
    assert kwargs["figi"] == "BBG123"
    assert kwargs["order_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert kwargs["price"].units == 1004
    assert kwargs["price"].nano == 95000000
    mock_client.sandbox.post_sandbox_order.assert_not_called()


def test_post_limit_order_maps_30052_to_trading_not_available() -> None:
    from grpc import StatusCode
    from t_tech.invest.exceptions import RequestError

    mock_client = MagicMock()
    mock_client.orders.post_order.side_effect = RequestError(
        StatusCode.INVALID_ARGUMENT, "30052", MagicMock(message="Instrument forbidden for trading by API")
    )

    with (
        patch("bond_monitor.infrastructure.tinvest.trading_client._open_client") as open_client,
        pytest.raises(TradingNotAvailableError, match="30052"),
    ):
        open_client.return_value.__enter__.return_value = mock_client
        post_limit_order(
            "token",
            AccountKind.PRODUCTION,
            account_id="acc-1",
            figi="BBG123",
            direction="BUY",
            lots=Lots(1),
            price_pct=PriceUnitPct(100.0),
            face_value=1000.0,
            request_uid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
