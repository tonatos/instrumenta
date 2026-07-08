"""Tests for POST /api/v1/portfolios/{id}/orders/preview."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bond_monitor.application.bonds.bond_service import BondService
from conftest import attach_trading_portfolio, portfolio_client
from factories import make_bond, make_infra_account_snapshot


def test_preview_order_returns_pricing_for_buy_suggestion() -> None:
    bond = make_bond(isin="RU000A109908", figi="FIGI-BUY", price=95.5, accrued_interest=1.01)
    universe = type("U", (), {"bonds": [bond]})()
    with portfolio_client("Order Preview") as (client, pid):
        attach_trading_portfolio(client, pid, auto_compose=False)
        with (
            patch.object(BondService, "load_universe", return_value=universe),
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_infra_account_snapshot(150_000.0),
            ),
            patch(
                "bond_monitor.application.trading.broker.preview_order_price",
                return_value=None,
            ),
        ):
            resp = client.post(
                f"/api/v1/portfolios/{pid}/orders/preview",
                json={
                    "isin": "RU000A109908",
                    "direction": "BUY",
                    "lots": 1,
                    "price_pct": 95.5,
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["order_lots"] == 1
        assert body["local_total_amount_rub"] == 956.01
        assert body["sufficient_cash"] is True
        assert body["preview_source"] == "moex"
        assert body["market_price_pct"] == pytest.approx(95.5)
        assert body["face_value_rub"] == pytest.approx(1000.0)
