"""Tests for queue-based position sell API (sandbox only)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.read_client import TradeAvailability
from bond_monitor.infrastructure.tinvest.trading_client import (
    BondPosition,
    OrderPricePreview,
    OrderState,
    PostOrderResult,
)
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_infra_account_snapshot


def _trade_available(*, figi: str = "FIGI123") -> TradeAvailability:
    return TradeAvailability(
        api_trade_available_flag=True,
        buy_available_flag=True,
        sell_available_flag=True,
        figi=figi,
        instrument_uid="uid-123",
        lot_size=1,
    )


def _snapshot_with_position(
    *,
    account_id: str,
    figi: str = "FIGI123",
    lots: int = 3,
    quantity: int | None = None,
    money_rub: float = 150_000.0,
) -> object:
    bond_quantity = quantity if quantity is not None else lots
    return make_infra_account_snapshot(
        money_rub,
        account_id=account_id,
        bond_positions={
            figi: BondPosition(
                figi=figi,
                instrument_uid="uid-123",
                ticker="TEST",
                quantity=bond_quantity,
                lots=lots,
                blocked=0,
                current_price_pct=PriceUnitPct(99.5),
                current_nkd_rub=Rub(10.0),
                average_price_pct=PriceUnitPct(98.0),
            )
        },
    )


def _prepare_sandbox_portfolio_with_bonds(
    client: TestClient,
    pid: str,
    *,
    figi: str = "FIGI123",
    actual_lots: int = 3,
) -> tuple[str, str]:
    account_id = f"acc-{uuid.uuid4().hex[:10]}"
    empty_snapshot = make_infra_account_snapshot(150_000.0, account_id=account_id)
    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=empty_snapshot,
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value=figi,
        ),
        patch(
            "bond_monitor.application.trading.broker.ensure_order_instrument",
            return_value=_trade_available(figi=figi),
        ),
    ):
        attach_trading_portfolio(
            client,
            pid,
            account_id=account_id,
            money_rub=150_000.0,
            figi=figi,
        )

    portfolio = client.get(f"/api/v1/portfolios/{pid}").json()
    isin = portfolio["data"]["positions"][0]["isin"]
    position_figi = portfolio["data"]["positions"][0].get("figi") or figi
    lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
    bond_quantity = actual_lots * lot_size

    filled_snapshot = _snapshot_with_position(
        account_id=account_id,
        figi=position_figi,
        lots=actual_lots,
        quantity=bond_quantity,
        money_rub=150_000.0,
    )
    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=filled_snapshot,
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.ensure_order_instrument",
            return_value=_trade_available(figi=position_figi),
        ),
    ):
        sync = client.post(f"/api/v1/portfolios/{pid}/sync")
        assert sync.status_code == 201, sync.text

    return isin, account_id


def test_queue_sell_rejects_production_account(client: TestClient) -> None:
    account_id = f"acc-{uuid.uuid4().hex[:10]}"
    snapshot = make_infra_account_snapshot(150_000.0, account_id=account_id)
    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=snapshot,
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI_PROD",
        ),
    ):
        with portfolio_client("Prod sell") as (test_client, pid):
            test_client.post(f"/api/v1/portfolios/{pid}/auto-compose")
            resp = test_client.post(
                f"/api/v1/portfolios/{pid}/attach",
                json={"account_id": account_id, "kind": "production"},
            )
            assert resp.status_code == 201, resp.text
            portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
            isin = portfolio["data"]["positions"][0]["isin"]
            sell = test_client.post(
                f"/api/v1/portfolios/{pid}/positions/{isin}/queue-sell",
                json={"lots": 1, "price_pct": 99.0},
            )
            assert sell.status_code == 400
            assert "песочнице" in sell.json()["detail"]


def test_sell_quote_returns_market_minus_buffer(client: TestClient) -> None:
    with portfolio_client("Sell quote") as (test_client, pid):
        isin, account_id = _prepare_sandbox_portfolio_with_bonds(test_client, pid)
        portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
        position_figi = portfolio["data"]["positions"][0].get("figi") or "FIGI123"
        lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
        filled = _snapshot_with_position(
            account_id=account_id,
            figi=position_figi,
            lots=3,
            quantity=3 * lot_size,
        )
        with patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=filled,
        ):
            resp = test_client.get(
                f"/api/v1/portfolios/{pid}/positions/{isin}/sell-quote",
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["market_price_pct"] == 99.5
        assert body["suggested_price_pct"] == 99.0025
        assert body["available_lots"] == 3
        assert body["sell_buffer_label"] == "0.5%"


def test_queue_sell_without_price_uses_suggested(client: TestClient) -> None:
    with portfolio_client("Queue sell default price") as (test_client, pid):
        isin, account_id = _prepare_sandbox_portfolio_with_bonds(test_client, pid)
        portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
        position_figi = portfolio["data"]["positions"][0].get("figi") or "FIGI123"
        lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
        filled = _snapshot_with_position(
            account_id=account_id,
            figi=position_figi,
            lots=3,
            quantity=3 * lot_size,
        )
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            resp = test_client.post(
                f"/api/v1/portfolios/{pid}/positions/{isin}/queue-sell",
                json={"lots": 2},
            )
        assert resp.status_code == 200, resp.text
        sells = [
            op for op in resp.json()["pending_operations"] if op["kind"] == "manual_sell"
        ]
        assert len(sells) == 1
        assert sells[0]["suggested_price_pct"] == 99.0025


def test_sell_position_preview_returns_sell_direction(client: TestClient) -> None:
    with portfolio_client("Sell preview") as (test_client, pid):
        isin, account_id = _prepare_sandbox_portfolio_with_bonds(test_client, pid)
        portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
        position_figi = portfolio["data"]["positions"][0].get("figi") or "FIGI123"
        lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
        filled = _snapshot_with_position(
            account_id=account_id,
            figi=position_figi,
            lots=3,
            quantity=3 * lot_size,
        )
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.ensure_order_instrument",
                return_value=_trade_available(figi=position_figi),
            ),
            patch(
                "bond_monitor.application.trading.broker.preview_order_price",
                return_value=OrderPricePreview(
                    lots_requested=2,
                    clean_amount_rub=Rub(1_990.0),
                    aci_amount_rub=Rub(20.0),
                    total_order_amount_rub=Rub(2_010.0),
                    executed_commission_rub=Rub(5.0),
                    deal_commission_rub=None,
                ),
            ) as preview_mock,
        ):
            resp = test_client.post(
                f"/api/v1/portfolios/{pid}/positions/{isin}/sell-preview",
                json={"lots": 2, "price_pct": 99.5},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["order_lots"] == 2
        assert body["available_lots"] == 3
        assert body["sufficient_lots"] is True
        assert body["suggested_price_pct"] is not None
        assert body["preview_source"] == "broker"
        preview_mock.assert_called_once()
        assert preview_mock.call_args.kwargs["direction"] == "SELL"


def test_queue_sell_adds_manual_sell_to_sync(client: TestClient) -> None:
    with portfolio_client("Queue sell") as (test_client, pid):
        isin, account_id = _prepare_sandbox_portfolio_with_bonds(test_client, pid)
        portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
        position_figi = portfolio["data"]["positions"][0].get("figi") or "FIGI123"
        lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
        filled = _snapshot_with_position(
            account_id=account_id,
            figi=position_figi,
            lots=3,
            quantity=3 * lot_size,
        )
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            resp = test_client.post(
                f"/api/v1/portfolios/{pid}/positions/{isin}/queue-sell",
                json={"lots": 2, "price_pct": 99.0},
            )
        assert resp.status_code == 200, resp.text
        sells = [
            op for op in resp.json()["pending_operations"] if op["kind"] == "manual_sell"
        ]
        assert len(sells) == 1
        assert sells[0]["isin"] == isin
        assert sells[0]["lots"] == 2
        assert sells[0]["suggested_price_pct"] == 99.0


def test_confirm_manual_sell_posts_limit_order(client: TestClient) -> None:
    with portfolio_client("Confirm sell") as (test_client, pid):
        isin, account_id = _prepare_sandbox_portfolio_with_bonds(test_client, pid)
        portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
        position_figi = portfolio["data"]["positions"][0].get("figi") or "FIGI123"
        lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
        filled = _snapshot_with_position(
            account_id=account_id,
            figi=position_figi,
            lots=3,
            quantity=3 * lot_size,
        )
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            queue = test_client.post(
                f"/api/v1/portfolios/{pid}/positions/{isin}/queue-sell",
                json={"lots": 2, "price_pct": 99.0},
            )
        assert queue.status_code == 200, queue.text
        op_id = next(
            op["id"]
            for op in queue.json()["pending_operations"]
            if op["kind"] == "manual_sell"
        )

        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.ensure_order_instrument",
                return_value=_trade_available(figi=position_figi),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_order_state",
                return_value=OrderState(
                    order_id="sell-order-1",
                    execution_report_status="EXECUTION_REPORT_STATUS_NEW",
                    figi=position_figi,
                    direction="SELL",
                    lots_executed=0,
                    lots_requested=2,
                    executed_price_pct=None,
                    initial_order_price_rub=None,
                    total_order_amount_rub=Rub(2_000.0),
                    order_date=None,
                ),
            ),
            patch(
                "bond_monitor.application.trading.broker.post_limit_order",
                return_value=PostOrderResult(
                    order_id="sell-order-1",
                    request_uid="uid-sell-1",
                    execution_report_status="EXECUTION_REPORT_STATUS_NEW",
                    lots_executed=0,
                    lots_requested=2,
                    executed_price_pct=None,
                    initial_order_price_rub=None,
                    total_order_amount_rub=Rub(2_000.0),
                    initial_commission_rub=Rub(3.0),
                ),
            ) as sell_mock,
        ):
            resp = test_client.post(
                f"/api/v1/portfolios/{pid}/pending-operations/{op_id}/confirm",
                json={"lots": 2, "price_pct": 99.0},
            )
        assert resp.status_code == 201, resp.text
        sell_mock.assert_called_once()
        assert sell_mock.call_args.kwargs["direction"] == "SELL"


def test_dismiss_manual_sell_removes_from_queue(client: TestClient) -> None:
    with portfolio_client("Dismiss sell") as (test_client, pid):
        isin, account_id = _prepare_sandbox_portfolio_with_bonds(test_client, pid)
        portfolio = test_client.get(f"/api/v1/portfolios/{pid}").json()
        position_figi = portfolio["data"]["positions"][0].get("figi") or "FIGI123"
        lot_size = portfolio["data"]["positions"][0].get("lot_size") or 1
        filled = _snapshot_with_position(
            account_id=account_id,
            figi=position_figi,
            lots=3,
            quantity=3 * lot_size,
        )
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            queue = test_client.post(
                f"/api/v1/portfolios/{pid}/positions/{isin}/queue-sell",
                json={"lots": 2, "price_pct": 99.0},
            )
        assert queue.status_code == 200, queue.text
        op_id = next(
            op["id"]
            for op in queue.json()["pending_operations"]
            if op["kind"] == "manual_sell"
        )

        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=filled,
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
        ):
            resp = test_client.post(
                f"/api/v1/portfolios/{pid}/pending-operations/{op_id}/dismiss",
            )
        assert resp.status_code == 200, resp.text
        assert not any(
            op["kind"] == "manual_sell" for op in resp.json()["pending_operations"]
        )
