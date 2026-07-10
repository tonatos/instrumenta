"""API: trading plan built from live broker snapshot."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from bond_monitor.application.bonds.bond_service import BondLoadResult, BondService
from conftest import portfolio_client
from factories import make_bond, make_snapshot_with_bonds


def test_get_plan_trading_includes_cashflow_from_account_holdings() -> None:
    maturity = date.today() + timedelta(days=180)
    bond = make_bond(
        isin="RU000TEST",
        secid="TEST01",
        figi="BBG0BOND",
        maturity=maturity,
        coupon_rate=12.0,
        coupon_period_days=30,
        next_coupon_date=date.today() + timedelta(days=30),
    )
    horizon = (date.today() + timedelta(days=365)).isoformat()
    with portfolio_client("Trading Plan Live", horizon_date=horizon) as (client, pid):
        snapshot = make_snapshot_with_bonds(50_000.0)
        with (
            patch.object(
                BondService,
                "load_universe",
                return_value=BondLoadResult(bonds=[bond], source="test"),
            ),
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
                return_value="BBG0BOND",
            ),
        ):
            attach = client.post(
                f"/api/v1/portfolios/{pid}/attach",
                json={"account_id": "acc-bonds", "kind": "sandbox"},
            )
            assert attach.status_code == 201, attach.text

            plan_resp = client.get(f"/api/v1/portfolios/{pid}/plan")
            assert plan_resp.status_code == 200, plan_resp.text
            body = plan_resp.json()
            assert body["invested_capital_rub"] > 0
            assert len(body["cashflow"]) > 0
