"""Tests for account preview and sandbox clear before trading attach."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import PostOrderResult
from bond_monitor.main import create_app
from conftest import linked_trading_account, portfolio_client
from factories import make_account_snapshot, make_infra_account_snapshot, make_snapshot_with_bonds


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=create_app())


def test_account_preview_shows_linked_portfolio_and_blocks_attach(client: TestClient) -> None:
    account_id = "acc-linked"
    with (
        linked_trading_account(account_id=account_id) as (client, linked_pid, _),
        portfolio_client("Новый портфель") as (_, new_pid),
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(150_000.0, account_id=account_id),
        ),
    ):
        resp = client.get(
            f"/api/v1/portfolios/{new_pid}/account-preview",
            params={"account_id": account_id, "kind": "sandbox"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["linked_portfolio"] == {
        "id": linked_pid,
        "name": "Уже в торговле",
    }
    assert body["can_attach"] is False
    assert any("привязан" in blocker.lower() for blocker in body["blockers"])


def test_account_preview_returns_positions_and_blockers(client: TestClient) -> None:
    with portfolio_client() as (client, pid), patch(
        "bond_monitor.application.trading.broker.get_account_snapshot",
        return_value=make_snapshot_with_bonds(),
    ):
        resp = client.get(
            f"/api/v1/portfolios/{pid}/account-preview",
            params={"account_id": "acc-bonds", "kind": "sandbox"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["money_rub"] == 50_000.0
    assert len(body["bond_positions"]) == 1
    assert body["bond_positions"][0]["ticker"] == "SU26238"
    assert body["bond_positions"][0]["lots"] == 1
    assert body["can_attach"] is True
    assert any("облигации" in w.lower() for w in body["warnings"])


def test_clear_account_rejected_for_production(client: TestClient) -> None:
    with portfolio_client() as (client, pid):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/clear-account",
            json={"account_id": "acc-prod", "kind": "production"},
        )

    assert resp.status_code == 400, resp.text
    assert "песочниц" in resp.json()["detail"].lower()


def test_clear_account_sells_bonds_in_sandbox(client: TestClient) -> None:
    empty_snapshot = make_infra_account_snapshot(
        160_000.0,
        account_id="acc-bonds",
    )

    from bond_monitor.infrastructure.tinvest.read_client import TradeAvailability

    trade_ok = TradeAvailability(
        api_trade_available_flag=True,
        buy_available_flag=True,
        sell_available_flag=True,
        figi="BBG0BOND",
        instrument_uid="uid-1",
        lot_size=10,
    )

    with (
        portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            side_effect=[make_snapshot_with_bonds(), empty_snapshot],
        ),
        patch(
            "bond_monitor.application.trading.broker.check_trade_available",
            return_value=trade_ok,
        ),
        patch(
            "bond_monitor.application.trading.broker.post_market_sell_order",
            return_value=PostOrderResult(
                order_id="ord-1",
                request_uid="uid-1",
                execution_report_status="EXECUTION_REPORT_STATUS_FILL",
                lots_executed=1,
                lots_requested=1,
                executed_price_pct=PriceUnitPct(95.0),
                initial_order_price_rub=None,
                total_order_amount_rub=Rub(9_550.0),
                initial_commission_rub=None,
            ),
        ) as sell_mock,
    ):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/clear-account",
            json={"account_id": "acc-bonds", "kind": "sandbox"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sold_count"] == 1
    assert body["money_rub"] == 160_000.0
    assert body["bond_positions"] == []
    sell_mock.assert_called_once()
    assert sell_mock.call_args.kwargs["instrument_uid"] == "uid-1"
    assert sell_mock.call_args.kwargs["figi"] == "BBG0BOND"


def test_clear_account_resets_sandbox_when_sell_fails(client: TestClient) -> None:
    from bond_monitor.infrastructure.tinvest.read_client import TradeAvailability
    from bond_monitor.infrastructure.tinvest.trading_client import TradingClientError

    fresh_snapshot = make_infra_account_snapshot(150_000.0, account_id="acc-new")

    trade_ok = TradeAvailability(
        api_trade_available_flag=False,
        buy_available_flag=False,
        sell_available_flag=False,
        figi="BBG0BOND",
        instrument_uid="uid-1",
        lot_size=10,
    )

    with (
        portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            side_effect=[make_snapshot_with_bonds(), fresh_snapshot],
        ),
        patch(
            "bond_monitor.application.trading.broker.check_trade_available",
            return_value=trade_ok,
        ),
        patch(
            "bond_monitor.application.trading.broker.post_market_sell_order",
            side_effect=TradingClientError("sell failed"),
        ),
        patch(
            "bond_monitor.application.trading.broker.close_sandbox_account",
        ) as close_mock,
        patch(
            "bond_monitor.application.trading.broker.open_sandbox_account",
            return_value="acc-new",
        ),
        patch(
            "bond_monitor.application.trading.broker.sandbox_pay_in",
            return_value=Rub(150_000.0),
        ),
    ):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/clear-account",
            json={"account_id": "acc-bonds", "kind": "sandbox"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_attach"] is True
    assert body["account_replaced"] == {"old_id": "acc-bonds", "new_id": "acc-new"}
    assert body["reset_note"]
    close_mock.assert_called_once()


def test_clear_account_uses_custom_pay_in_rub(client: TestClient) -> None:
    from bond_monitor.infrastructure.tinvest.read_client import TradeAvailability
    from bond_monitor.infrastructure.tinvest.trading_client import TradingClientError

    fresh_snapshot = make_infra_account_snapshot(250_000.0, account_id="acc-new")

    with (
        portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            side_effect=[make_snapshot_with_bonds(), fresh_snapshot],
        ),
        patch(
            "bond_monitor.application.trading.broker.check_trade_available",
            return_value=TradeAvailability(
                api_trade_available_flag=True,
                buy_available_flag=True,
                sell_available_flag=True,
                figi="BBG0BOND",
                instrument_uid="uid-1",
                lot_size=10,
            ),
        ),
        patch(
            "bond_monitor.application.trading.broker.post_market_sell_order",
            side_effect=TradingClientError("sell failed"),
        ),
        patch("bond_monitor.application.trading.broker.close_sandbox_account"),
        patch(
            "bond_monitor.application.trading.broker.open_sandbox_account",
            return_value="acc-new",
        ),
        patch(
            "bond_monitor.application.trading.broker.sandbox_pay_in",
            return_value=Rub(250_000.0),
        ) as pay_in_mock,
    ):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/clear-account",
            json={
                "account_id": "acc-bonds",
                "kind": "sandbox",
                "pay_in_rub": 250_000.0,
            },
        )

    assert resp.status_code == 200, resp.text
    pay_in_mock.assert_called_once()
    assert float(pay_in_mock.call_args.args[2]) == 250_000.0
