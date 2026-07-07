"""Tests for auto top-up apply during trading sync."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

from litestar.testing import TestClient

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot, OperationRecord
from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client() -> Generator[tuple[TestClient, str], None, None]:
    with TestClient(app=create_app()) as client:
        resp = client.post(
            "/api/v1/portfolios/",
            json={
                "name": "Top-up Sync",
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


def _snapshot(money_rub: float) -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-clean",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(money_rub),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _input_operation(amount: float) -> OperationRecord:
    return OperationRecord(
        id="op-input-1",
        type="OPERATION_TYPE_INPUT",
        state="EXECUTED",
        date=datetime.now(UTC),
        figi="",
        instrument_uid="",
        instrument_type="",
        payment_rub=Rub(amount),
        quantity=0,
        price_pct=None,
        commission_rub=None,
    )


def _attach(client: TestClient, pid: str) -> None:
    with (
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=_snapshot(150_000.0),
        ),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
            return_value="FIGI123",
        ),
    ):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": "acc-clean", "kind": "sandbox"},
        )
        assert resp.status_code == 201, resp.text


def test_sync_auto_applies_top_up_and_creates_top_up_buy() -> None:
    with _portfolio_client() as (client, pid):
        _attach(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(200_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[_input_operation(50_000.0)],
            ),
        ):
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
    with _portfolio_client() as (client, pid):
        _attach(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(200_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[_input_operation(50_000.0)],
            ),
        ):
            first = client.post(f"/api/v1/portfolios/{pid}/sync").json()
        assert first["top_up_auto_applied"] is True
        first_batch_ids = {
            op["top_up_batch_id"]
            for op in first["pending_operations"]
            if op["kind"] == "top_up_buy"
        }
        assert first_batch_ids

        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(200_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[_input_operation(50_000.0)],
            ),
        ):
            second = client.post(f"/api/v1/portfolios/{pid}/sync").json()

        assert second["top_up_auto_applied"] is False
        second_batch_ids = {
            op["top_up_batch_id"]
            for op in second["pending_operations"]
            if op["kind"] == "top_up_buy"
        }
        assert second_batch_ids == first_batch_ids


def test_attach_sets_top_up_watermark() -> None:
    with _portfolio_client() as (client, pid):
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(150_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.trading_service.resolve_figi_for_isin",
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
    with _portfolio_client() as (client, pid):
        _attach(client, pid)
        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(200_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[_input_operation(50_000.0)],
            ),
        ):
            sync = client.post(f"/api/v1/portfolios/{pid}/sync").json()

        batch_id = next(
            op["top_up_batch_id"]
            for op in sync["pending_operations"]
            if op["kind"] == "top_up_buy"
        )
        portfolio_before = client.get(f"/api/v1/portfolios/{pid}").json()
        acknowledged_before = portfolio_before["data"].get("acknowledged_top_ups_rub", 0.0)

        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(200_000.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[_input_operation(50_000.0)],
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/top-up-batches/{batch_id}/cancel")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert not any(op["kind"] == "top_up_buy" for op in body["pending_operations"])
        portfolio_after = client.get(f"/api/v1/portfolios/{pid}").json()
        assert portfolio_after["data"].get("acknowledged_top_ups_rub", 0.0) < acknowledged_before
