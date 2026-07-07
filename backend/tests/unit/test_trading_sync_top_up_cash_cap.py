"""Top-up sync must not allocate beyond free cash after pending buys."""

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
                "name": "Top-up cash cap",
                "initial_amount_rub": 20_000.0,
                "horizon_date": "2027-06-01",
                "risk_profile": "normal",
            },
        )
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


def test_sync_top_up_skipped_when_cash_already_committed_to_unfilled_positions() -> None:
    """При 4 779 ₽ и незакрытых 11 лотах top-up не должен создавать новые покупки."""
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
            client.post(
                f"/api/v1/portfolios/{pid}/attach",
                json={"account_id": "acc-clean", "kind": "sandbox"},
            )

        with (
            patch(
                "bond_monitor.application.trading.trading_service.get_account_snapshot",
                return_value=_snapshot(4779.0),
            ),
            patch(
                "bond_monitor.application.trading.trading_service.get_account_operations",
                return_value=[_input_operation(50_000.0)],
            ),
        ):
            resp = client.post(f"/api/v1/portfolios/{pid}/sync")

        body = resp.json()
        assert body["top_up_auto_applied"] is False
        assert not any(op["kind"] == "top_up_buy" for op in body["pending_operations"])

        plan = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        for point in plan["value_timeline"]:
            assert point["cash_rub"] >= -0.01
