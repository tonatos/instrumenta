"""Tests for infrastructure.tinvest.trading_client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import (
    PostOrderResult,
    TradingNotAvailableError,
    _classify_position,
    _order_state_from_proto,
    get_account_snapshot,
    post_limit_order,
    post_market_sell_order,
)


# ── Snapshot ──────────────────────────────────────────────────────────────────


def _quotation(value: float) -> SimpleNamespace:
    units = int(value)
    nano = int(round((value - units) * 1_000_000_000))
    return SimpleNamespace(units=units, nano=nano)


def _bond_portfolio_position(
    *,
    current_price_rub: float,
    average_price_rub: float,
    figi: str = "TCS00A10AU73",
) -> SimpleNamespace:
    return SimpleNamespace(
        instrument_type="bond",
        figi=figi,
        instrument_uid="uid-gtlk",
        ticker="RU000A10AU73",
        quantity=_quotation(66),
        quantity_lots=_quotation(66),
        blocked=_quotation(0),
        current_price=_quotation(current_price_rub),
        current_nkd=SimpleNamespace(units=2, nano=0, currency="rub"),
        average_position_price=SimpleNamespace(
            units=int(average_price_rub),
            nano=int(round((average_price_rub % 1) * 1_000_000_000)),
            currency="rub",
        ),
    )


def test_classify_bond_converts_portfolio_ruble_price_to_pct() -> None:
    """getPortfolio отдаёт current_price в ₽, а не в % от номинала."""
    kind, bond = _classify_position(
        _bond_portfolio_position(current_price_rub=1004.4, average_price_rub=1003.1),
        nominal_rub=1000.0,
    )

    assert kind == "bond"
    assert bond is not None
    assert float(bond.current_price_pct) == pytest.approx(100.44)
    assert float(bond.average_price_pct) == pytest.approx(100.31)


def test_classify_bond_without_nominal_leaves_price_pct_none() -> None:
    kind, bond = _classify_position(
        _bond_portfolio_position(current_price_rub=1004.4, average_price_rub=1003.1),
        nominal_rub=None,
    )

    assert kind == "bond"
    assert bond is not None
    assert bond.current_price_pct is None
    assert bond.average_price_pct is None


def test_order_state_converts_initial_security_price_rub_to_pct() -> None:
    from t_tech.invest import OrderDirection as ProtoOrderDirection
    from t_tech.invest.schemas import OrderExecutionReportStatus

    state = SimpleNamespace(
        order_id="order-1",
        execution_report_status=OrderExecutionReportStatus.EXECUTION_REPORT_STATUS_NEW,
        figi="FIGI_BOND",
        direction=ProtoOrderDirection.ORDER_DIRECTION_SELL,
        lots_executed=0,
        lots_requested=36,
        executed_order_price=None,
        initial_security_price=_quotation(906.0),
        initial_order_price=SimpleNamespace(units=32616, nano=0, currency="rub"),
        total_order_amount=SimpleNamespace(units=32616, nano=0, currency="rub"),
        order_date=None,
        order_request_id="uid-1",
        initial_commission=SimpleNamespace(units=326, nano=0, currency="rub"),
        instrument_uid="uid-bond",
    )

    result = _order_state_from_proto(state, face_value=1000.0)

    assert float(result.price_pct) == pytest.approx(90.6)


def test_get_account_snapshot_fetches_nominal_for_bond_prices() -> None:
    portfolio = MagicMock()
    portfolio.total_amount_currencies = SimpleNamespace(units=100_000, nano=0, currency="rub")
    portfolio.positions = [
        _bond_portfolio_position(current_price_rub=1009, average_price_rub=1005),
    ]

    bond_instrument = MagicMock()
    bond_instrument.nominal = SimpleNamespace(units=1000, nano=0, currency="rub")

    mock_client = MagicMock()
    mock_client.operations.get_portfolio.return_value = portfolio
    mock_client.instruments.bond_by.return_value = MagicMock(instrument=bond_instrument)

    with patch(
        "bond_monitor.infrastructure.tinvest.trading_client._open_client"
    ) as open_client:
        open_client.return_value.__enter__.return_value = mock_client
        snapshot = get_account_snapshot("token", AccountKind.SANDBOX, "acc-1")

    bond = snapshot.bond_positions["TCS00A10AU73"]
    assert float(bond.current_price_pct) == pytest.approx(100.9)
    assert float(bond.average_price_pct) == pytest.approx(100.5)
    assert snapshot.money_rub == Rub(100_000.0)


def test_get_account_snapshot_reads_blocked_money_from_positions() -> None:
    portfolio = MagicMock()
    portfolio.total_amount_currencies = SimpleNamespace(units=50_000, nano=0, currency="rub")
    portfolio.positions = [
        SimpleNamespace(
            instrument_type="currency",
            ticker="RUB000UTSTOM",
            quantity=_quotation(50_000),
            current_price=_quotation(1),
        )
    ]

    positions_resp = MagicMock()
    positions_resp.blocked = [
        SimpleNamespace(currency="rub", units=45_641, nano=500_000_000)
    ]

    mock_client = MagicMock()
    mock_client.operations.get_portfolio.return_value = portfolio
    mock_client.operations.get_positions.return_value = positions_resp

    with patch(
        "bond_monitor.infrastructure.tinvest.trading_client._open_client"
    ) as open_client:
        open_client.return_value.__enter__.return_value = mock_client
        snapshot = get_account_snapshot("token", AccountKind.PRODUCTION, "acc-1")

    assert snapshot.money_rub == Rub(50_000.0)
    assert float(snapshot.blocked_money_rub) == pytest.approx(45_641.5)
    mock_client.operations.get_positions.assert_called_once_with(account_id="acc-1")


# ── post_order ────────────────────────────────────────────────────────────────


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


# ── market sell ─────────────────────────────────────────────────────────────


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
    assert float(kwargs["price_pct"]) == 97.0
