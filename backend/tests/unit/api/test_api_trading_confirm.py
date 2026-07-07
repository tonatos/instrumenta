"""Tests for confirm/cancel pending operations API."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from litestar.testing import TestClient

from bond_monitor.application.bonds.bond_service import BondLoadResult, BondService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
    TradeRecord,
)
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub, order_amount_rub
from bond_monitor.infrastructure.tinvest.read_client import TradeAvailability
from bond_monitor.infrastructure.tinvest.trading_client import (
    OrderState,
    PostOrderResult,
)
from conftest import portfolio_client
from factories import make_infra_account_snapshot


def _trade_available() -> TradeAvailability:
    return TradeAvailability(
        api_trade_available_flag=True,
        buy_available_flag=True,
        sell_available_flag=True,
        figi="FIGI123",
        instrument_uid="uid-123",
        lot_size=1,
    )


def _attach(client: TestClient, pid: str) -> str:
    account_id = f"acc-{uuid.uuid4().hex[:10]}"
    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_infra_account_snapshot(150_000.0, account_id=account_id),
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
        patch(
            "bond_monitor.application.trading.broker.ensure_order_instrument",
            return_value=_trade_available(),
        ),
    ):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": account_id, "kind": "sandbox"},
        )
    return account_id


def _order_state() -> OrderState:
    return OrderState(
        order_id="order-abc",
        execution_report_status="EXECUTION_REPORT_STATUS_NEW",
        figi="FIGI123",
        direction="BUY",
        lots_executed=0,
        lots_requested=1,
        executed_price_pct=None,
        initial_order_price_rub=None,
        total_order_amount_rub=Rub(1000.0),
        order_date=None,
    )


def test_confirm_pending_submits_order_and_returns_in_progress() -> None:
    with portfolio_client("Confirm Test") as (client, pid):
        account_id = _attach(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_infra_account_snapshot(150_000.0, account_id=account_id),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.get_order_state",
                return_value=_order_state(),
            ),
            patch(
                "bond_monitor.application.trading.broker.ensure_order_instrument",
                return_value=_trade_available(),
            ),
            patch(
                "bond_monitor.application.trading.broker.post_limit_order",
                return_value=PostOrderResult(
                    order_id="order-abc",
                    request_uid="uid-1",
                    execution_report_status="EXECUTION_REPORT_STATUS_NEW",
                    lots_executed=0,
                    lots_requested=1,
                    executed_price_pct=None,
                    initial_order_price_rub=None,
                    total_order_amount_rub=Rub(1000.0),
                    initial_commission_rub=None,
                ),
            ) as mock_post,
        ):
            sync = client.post(f"/api/v1/portfolios/{pid}/sync").json()
            buys = [op for op in sync["pending_operations"] if op["kind"] == "initial_buy"]
            assert buys, "expected initial_buy pending"
            op_id = buys[0]["id"]

            resp = client.post(
                f"/api/v1/portfolios/{pid}/pending-operations/{op_id}/confirm",
                json={"lots": buys[0]["lots"], "price_pct": buys[0]["suggested_price_pct"]},
            )

        assert resp.status_code == 201, resp.text
        mock_post.assert_called_once()
        body = resp.json()
        matched = [op for op in body["pending_operations"] if op["id"] == op_id]
        assert matched
        assert matched[0]["status"] == "in_progress"
        assert matched[0]["active_order_id"] == "order-abc"
        assert matched[0]["active_order_lots"] == buys[0]["lots"]
        assert matched[0]["active_order_total_rub"] == pytest.approx(1000.0)
        assert matched[0]["active_order_price_pct"] == pytest.approx(
            buys[0]["suggested_price_pct"]
        )


def test_confirm_includes_accrued_interest_in_estimated_order_amount() -> None:
    """Подтверждение BUY передаёт в post_limit_order грязную сумму (чистая + НКД)."""
    with portfolio_client("Confirm Test") as (client, pid):
        account_id = _attach(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_infra_account_snapshot(150_000.0, account_id=account_id),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.get_order_state",
                return_value=_order_state(),
            ),
            patch(
                "bond_monitor.application.trading.broker.ensure_order_instrument",
                return_value=_trade_available(),
            ),
            patch(
                "bond_monitor.application.trading.broker.post_limit_order",
                return_value=PostOrderResult(
                    order_id="order-abc",
                    request_uid="uid-1",
                    execution_report_status="EXECUTION_REPORT_STATUS_NEW",
                    lots_executed=0,
                    lots_requested=1,
                    executed_price_pct=None,
                    initial_order_price_rub=None,
                    total_order_amount_rub=Rub(1000.0),
                    initial_commission_rub=None,
                ),
            ) as mock_post,
        ):
            sync = client.post(f"/api/v1/portfolios/{pid}/sync").json()
            buys = [op for op in sync["pending_operations"] if op["kind"] == "initial_buy"]
            assert buys, "expected initial_buy pending"
            op = buys[0]
            target_isin = op["isin"]
            order_lots = op["lots"]
            order_price = op["suggested_price_pct"]
            aci_rub = 12.5

            original_load = BondService.load_universe

            def _load_with_aci(self: BondService) -> BondLoadResult:
                result = original_load(self)
                for bond in result.bonds:
                    if bond.isin == target_isin:
                        bond.accrued_interest = aci_rub
                return result

            with patch.object(BondService, "load_universe", _load_with_aci):
                resp = client.post(
                    f"/api/v1/portfolios/{pid}/pending-operations/{op['id']}/confirm",
                    json={"lots": order_lots, "price_pct": order_price},
                )

        assert resp.status_code == 201, resp.text
        mock_post.assert_called_once()
        estimated = mock_post.call_args.kwargs["estimated_total_amount_rub"]
        expected = order_amount_rub(
            price_pct=PriceUnitPct(order_price),
            face_value=1000.0,
            lot_size=1,
            lots=Lots(order_lots),
            aci_rub=aci_rub,
        )
        assert estimated == pytest.approx(expected)
        clean_only = order_lots * 1000.0 * order_price / 100.0
        assert float(estimated) > clean_only


def test_refresh_trade_record_states_updates_amounts_from_broker() -> None:
    portfolio = Portfolio(
        name="Refresh",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
        mode=PortfolioMode.TRADING,
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
    )
    portfolio.trade_records = [
        TradeRecord(
            request_uid="uid1",
            account_id="acc-1",
            account_kind=AccountKind.SANDBOX,
            figi="FIGI123",
            direction="BUY",
            lots=2,
            order_id="order-abc",
            status="EXECUTION_REPORT_STATUS_NEW",
            total_order_amount_rub=1000.0,
            lots_executed=0,
        )
    ]
    service = TradingService(AsyncMock(), sandbox_token="token", production_token="token")

    updated_state = OrderState(
        order_id="order-abc",
        execution_report_status="EXECUTION_REPORT_STATUS_PARTIALLYFILL",
        figi="FIGI123",
        direction="BUY",
        lots_executed=1,
        lots_requested=2,
        executed_price_pct=None,
        initial_order_price_rub=None,
        total_order_amount_rub=Rub(1500.0),
        order_date=None,
    )

    with patch(
        "bond_monitor.application.trading.broker.get_order_state",
        return_value=updated_state,
    ):
        updated = service._sync._refresh_trade_record_states(portfolio, "token")

    assert updated >= 1
    tr = portfolio.trade_records[0]
    assert tr.status == "EXECUTION_REPORT_STATUS_PARTIALLYFILL"
    assert tr.lots_executed == 1
    assert tr.total_order_amount_rub == pytest.approx(1500.0)


def test_confirm_returns_400_for_unknown_op() -> None:
    with portfolio_client("Confirm Test") as (client, pid):
        account_id = _attach(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_infra_account_snapshot(150_000.0, account_id=account_id),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            resp = client.post(
                f"/api/v1/portfolios/{pid}/pending-operations/unknown-id/confirm",
                json={"lots": 1, "price_pct": 100.5},
            )
        assert resp.status_code == 400
