"""Tests for auto top-up apply during trading sync."""

from __future__ import annotations

import contextlib
from unittest.mock import patch

from conftest import attach_trading_portfolio, portfolio_client
from factories import make_account_snapshot, make_input_operation
from bond_monitor.infrastructure.tinvest.read_client import TradeAvailability


@contextlib.contextmanager
def _sync_patches(money_rub: float):
    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(money_rub),
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[make_input_operation(50_000.0)],
        ),
        patch(
            "bond_monitor.application.trading.broker.ensure_order_instrument",
            return_value=TradeAvailability(
                api_trade_available_flag=True,
                buy_available_flag=True,
                sell_available_flag=True,
                figi="FIGI123",
                instrument_uid="uid-123",
                lot_size=1,
            ),
        ),
    ):
        yield


def test_sync_auto_applies_top_up_and_creates_top_up_buy() -> None:
    with portfolio_client("Top-up Sync") as (client, pid):
        attach_trading_portfolio(client, pid)
        with _sync_patches(200_000.0):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["top_up_auto_applied"] is True
        assert body["top_up_distributed_rub"] > 0
        top_up_ops = [op for op in body["pending_operations"] if op["kind"] == "top_up_buy"]
        assert top_up_ops
        assert all(op.get("top_up_batch_id") for op in top_up_ops)
        assert body["has_pending_top_up"] is False


def test_sync_does_not_duplicate_top_up_while_batch_active() -> None:
    with portfolio_client("Top-up Sync") as (client, pid):
        attach_trading_portfolio(client, pid)
        with _sync_patches(200_000.0):
            first = client.post(f"/api/v1/portfolios/{pid}/sync").json()
        assert first["top_up_auto_applied"] is True
        first_batch_ids = {
            op["top_up_batch_id"]
            for op in first["pending_operations"]
            if op["kind"] == "top_up_buy"
        }
        assert first_batch_ids

        with _sync_patches(200_000.0):
            second = client.post(f"/api/v1/portfolios/{pid}/sync").json()

        assert second["top_up_auto_applied"] is False
        second_batch_ids = {
            op["top_up_batch_id"]
            for op in second["pending_operations"]
            if op["kind"] == "top_up_buy"
        }
        assert second_batch_ids == first_batch_ids


def test_attach_sets_top_up_watermark() -> None:
    with portfolio_client("Top-up Sync") as (client, pid):
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(150_000.0),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.resolve_figi_for_isin",
                return_value="FIGI123",
            ),
        ):
            client.post(f"/api/v1/portfolios/{pid}/auto-compose")
            resp = client.post(
                f"/api/v1/portfolios/{pid}/attach",
                json={"account_id": "acc-clean", "kind": "sandbox"},
            )
        body = resp.json()
        assert body["data"]["last_top_up_processed_at"] == body["data"]["trading_started_at"]


def test_cancel_top_up_batch_endpoint() -> None:
    with portfolio_client("Top-up Sync") as (client, pid):
        attach_trading_portfolio(client, pid)
        with _sync_patches(200_000.0):
            sync = client.post(f"/api/v1/portfolios/{pid}/sync").json()

        batch_id = next(
            op["top_up_batch_id"]
            for op in sync["pending_operations"]
            if op["kind"] == "top_up_buy"
        )
        portfolio_before = client.get(f"/api/v1/portfolios/{pid}").json()
        acknowledged_before = portfolio_before["data"].get("acknowledged_top_ups_rub", 0.0)

        with _sync_patches(200_000.0):
            resp = client.post(f"/api/v1/portfolios/{pid}/top-up-batches/{batch_id}/cancel")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        top_up_ops = [op for op in body["pending_operations"] if op["kind"] == "top_up_buy"]
        assert top_up_ops
        assert all(op.get("top_up_batch_id") != batch_id for op in top_up_ops)
        portfolio_after = client.get(f"/api/v1/portfolios/{pid}").json()
        assert portfolio_after["data"].get("acknowledged_top_ups_rub", 0.0) <= acknowledged_before


def test_cancel_top_up_batch_reapplies_on_follow_up_sync() -> None:
    """После отмены партии повторный sync снова распределяет пополнение."""
    with portfolio_client(
        "Top-up re-apply",
        initial_amount_rub=20_000.0,
        horizon_date="2027-06-01",
    ) as (client, pid):
        attach_trading_portfolio(client, pid)
        with _sync_patches(200_000.0):
            sync = client.post(f"/api/v1/portfolios/{pid}/sync").json()

        batch_id = next(
            op["top_up_batch_id"]
            for op in sync["pending_operations"]
            if op["kind"] == "top_up_buy"
        )

        with _sync_patches(200_000.0):
            after_cancel = client.post(
                f"/api/v1/portfolios/{pid}/top-up-batches/{batch_id}/cancel"
            ).json()

        assert after_cancel["top_up_auto_applied"] is True
        assert after_cancel["top_up_distributed_rub"] > 0
        top_up_ops = [op for op in after_cancel["pending_operations"] if op["kind"] == "top_up_buy"]
        assert top_up_ops
        assert any(op.get("top_up_batch_id") != batch_id for op in top_up_ops)


def test_sync_distributes_orphan_cash_without_fresh_input() -> None:
    """Кэш на счёте без свежего INPUT (watermark уже прошёл) — sync всё равно распределяет."""
    with portfolio_client(
        "Orphan cash sync",
        initial_amount_rub=20_000.0,
        horizon_date="2027-06-01",
    ) as (client, pid):
        attach_trading_portfolio(client, pid, money_rub=200_000.0)
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(200_000.0),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.ensure_order_instrument",
                return_value=TradeAvailability(
                    api_trade_available_flag=True,
                    buy_available_flag=True,
                    sell_available_flag=True,
                    figi="FIGI123",
                    instrument_uid="uid-123",
                    lot_size=1,
                ),
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["top_up_auto_applied"] is True
        assert body["top_up_distributed_rub"] > 0
        top_up_ops = [op for op in body["pending_operations"] if op["kind"] == "top_up_buy"]
        assert top_up_ops


def test_sync_top_up_skipped_when_cash_already_committed_to_unfilled_positions() -> None:
    """При 4 779 ₽ и незакрытых 11 лотах top-up не должен создавать новые покупки."""
    with portfolio_client(
        "Top-up cash cap",
        initial_amount_rub=20_000.0,
        horizon_date="2027-06-01",
    ) as (client, pid):
        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(150_000.0),
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
                return_value=TradeAvailability(
                    api_trade_available_flag=True,
                    buy_available_flag=True,
                    sell_available_flag=True,
                    figi="FIGI123",
                    instrument_uid="uid-123",
                    lot_size=1,
                ),
            ),
        ):
            client.post(f"/api/v1/portfolios/{pid}/auto-compose")
            client.post(
                f"/api/v1/portfolios/{pid}/attach",
                json={"account_id": "acc-clean", "kind": "sandbox"},
            )

        with (
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(4779.0),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[make_input_operation(50_000.0)],
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["top_up_auto_applied"] is False
        assert not any(op["kind"] == "top_up_buy" for op in body["pending_operations"])
