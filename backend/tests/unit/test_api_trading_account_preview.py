"""Tests for account preview and sandbox clear before trading attach."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    BondPosition,
    PostOrderResult,
)
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Preview Test") -> Generator[tuple[TestClient, str], None, None]:
    with TestClient(app=create_app()) as client:
        resp = client.post(
            "/api/v1/portfolios/",
            json={
                "name": name,
                "initial_amount_rub": 100_000.0,
                "horizon_date": "2027-01-01",
                "risk_profile": "normal",
            },
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        try:
            yield client, pid
        finally:
            client.delete(f"/api/v1/portfolios/{pid}")


def _snapshot_with_bonds(money_rub: float = 50_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-bonds",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money_rub),
        bond_positions={
            "BBG0BOND": BondPosition(
                figi="BBG0BOND",
                instrument_uid="uid-1",
                ticker="SU26238",
                quantity=10,
                lots=1,
                blocked=0,
                current_price_pct=PriceUnitPct(95.5),
                current_nkd_rub=Rub(12.0),
                average_price_pct=PriceUnitPct(94.0),
            )
        },
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app=create_app())


def test_account_preview_shows_linked_portfolio_and_blocks_attach(client: TestClient) -> None:
    clean_snapshot = AccountSnapshot(
        account_id="acc-linked",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(150_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    with (
        _portfolio_client("Уже в торговле") as (client, linked_pid),
        _portfolio_client("Новый портфель") as (_, new_pid),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=clean_snapshot,
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        attach_resp = client.post(
            f"/api/v1/portfolios/{linked_pid}/attach",
            json={"account_id": "acc-linked", "kind": "sandbox"},
        )
        assert attach_resp.status_code == 201, attach_resp.text

        resp = client.get(
            f"/api/v1/portfolios/{new_pid}/account-preview",
            params={"account_id": "acc-linked", "kind": "sandbox"},
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
    with _portfolio_client() as (client, pid), patch(
        "bond_monitor.application.trading.trading_service.get_account_snapshot",
        return_value=_snapshot_with_bonds(),
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
    assert body["can_attach"] is False
    assert any("облигации" in b.lower() for b in body["blockers"])


def test_clear_account_rejected_for_production(client: TestClient) -> None:
    with _portfolio_client() as (client, pid):
        resp = client.post(
            f"/api/v1/portfolios/{pid}/clear-account",
            json={"account_id": "acc-prod", "kind": "production"},
        )

    assert resp.status_code == 400, resp.text
    assert "песочниц" in resp.json()["detail"].lower()


def test_clear_account_sells_bonds_in_sandbox(client: TestClient) -> None:
    empty_snapshot = AccountSnapshot(
        account_id="acc-bonds",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(160_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
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
        _portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            side_effect=[_snapshot_with_bonds(), empty_snapshot],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.check_trade_available",
            return_value=trade_ok,
        ),
        patch(
            "bond_monitor.application.trading.trading_service.post_market_sell_order",
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

    fresh_snapshot = AccountSnapshot(
        account_id="acc-new",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(150_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    trade_ok = TradeAvailability(
        api_trade_available_flag=False,
        buy_available_flag=False,
        sell_available_flag=False,
        figi="BBG0BOND",
        instrument_uid="uid-1",
        lot_size=10,
    )

    with (
        _portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            side_effect=[_snapshot_with_bonds(), fresh_snapshot],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.check_trade_available",
            return_value=trade_ok,
        ),
        patch(
            "bond_monitor.application.trading.trading_service.post_market_sell_order",
            side_effect=TradingClientError("sell failed"),
        ),
        patch(
            "bond_monitor.application.trading.trading_service.close_sandbox_account",
        ) as close_mock,
        patch(
            "bond_monitor.application.trading.trading_service.open_sandbox_account",
            return_value="acc-new",
        ),
        patch(
            "bond_monitor.application.trading.trading_service.sandbox_pay_in",
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

    fresh_snapshot = AccountSnapshot(
        account_id="acc-new",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(250_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    with (
        _portfolio_client() as (client, pid), patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            side_effect=[_snapshot_with_bonds(), fresh_snapshot],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.check_trade_available",
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
            "bond_monitor.application.trading.trading_service.post_market_sell_order",
            side_effect=TradingClientError("sell failed"),
        ),
        patch("bond_monitor.application.trading.trading_service.close_sandbox_account"),
        patch(
            "bond_monitor.application.trading.trading_service.open_sandbox_account",
            return_value="acc-new",
        ),
        patch(
            "bond_monitor.application.trading.trading_service.sandbox_pay_in",
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
