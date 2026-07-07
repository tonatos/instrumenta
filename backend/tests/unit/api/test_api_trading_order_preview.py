"""Tests for order preview before confirming a pending BUY."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from litestar.testing import TestClient

from bond_monitor.application.trading.trading_service import OrderPreviewResult, TradingService
from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    AccountKind,
    PendingOperation,
)
from bond_monitor.domain.portfolio.planner import PortfolioPlan
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import OrderPricePreview
from bond_monitor.main import create_app
from factories import make_bond, make_infra_account_snapshot


def _bond(*, isin: str = "RU000A1", accrued_interest: float = 285.0) -> BondRecord:
    bond = make_bond(
        isin=isin,
        secid="MTS005",
        name="МТС-Банк05",
        maturity=date(2027, 6, 1),
        price=100.0,
        ytm=15.0,
        credit_rating="ruBBB",
        figi="FIGI_MTS",
        liquidity_flag=True,
        coupon_rate=12.0,
        coupon_period_days=180,
    )
    bond.accrued_interest = accrued_interest
    return bond


def _snapshot(*, money_rub: float = 150_000.0):
    return make_infra_account_snapshot(money_rub, account_id="acc-1")


def _portfolio() -> Portfolio:
    portfolio = Portfolio(
        name="Preview",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
        mode=PortfolioMode.TRADING,
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
    )
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000A1",
            secid="MTS005",
            name="МТС-Банк05",
            lots=1,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 1, 1),
            purchase_amount_rub=1000.0,
            coupon_rate=12.0,
            face_value=1000.0,
            maturity_date=date(2027, 6, 1),
            offer_date=None,
            coupon_period_days=180,
            source=PositionSourceType.INITIAL,
            figi="FIGI_MTS",
            actual_lots=0,
        )
    ]
    return portfolio


def _pending_op() -> PendingOperation:
    return PendingOperation(
        id="op-1",
        kind="initial_buy",
        isin="RU000A1",
        name="МТС-Банк05",
        lots=1,
        figi="FIGI_MTS",
        suggested_price_pct=100.4095,
        status="action_required",
        face_value_rub=1000.0,
        lot_size=1,
        aci_rub_per_bond=285.0,
    )


@pytest.mark.asyncio
async def test_preview_pending_operation_returns_broker_total_with_nkd() -> None:
    portfolio = _portfolio()
    repo = AsyncMock()
    service = TradingService(repo, sandbox_token="sandbox-token", production_token="prod-token")
    service._sync._ctx.get_trading_portfolio = AsyncMock(return_value=portfolio)  # type: ignore[method-assign]

    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=_snapshot(),
        ),
        patch(
            "bond_monitor.application.trading.order_use_case.build_plan",
            return_value=PortfolioPlan(portfolio=portfolio),
        ),
        patch(
            "bond_monitor.application.trading.order_use_case.compute_pending_operations",
            return_value=[_pending_op()],
        ),
        patch(
            "bond_monitor.application.trading.broker.preview_order_price",
            return_value=OrderPricePreview(
                lots_requested=1,
                clean_amount_rub=Rub(1_004.1),
                aci_amount_rub=Rub(285.0),
                total_order_amount_rub=Rub(1_313.6),
                executed_commission_rub=Rub(0.0),
                deal_commission_rub=Rub(24.5),
            ),
        ) as mock_preview,
    ):
        result = await service.preview_pending_operation(
            portfolio.id,
            "op-1",
            [_bond()],
            key_rate=14.5,
            tax_rate=0.18,
            today=date(2026, 7, 7),
            lots=1,
            price_pct=100.4095,
        )

    mock_preview.assert_called_once()
    assert result.order_lots == 1
    assert result.order_price_pct == pytest.approx(100.4095)
    assert result.aci_rub_per_bond == pytest.approx(285.0)
    assert result.local_total_amount_rub == pytest.approx(1_289.1, abs=0.02)
    assert result.broker_clean_amount_rub == pytest.approx(1_004.1)
    assert result.broker_aci_amount_rub == pytest.approx(285.0)
    assert result.broker_total_amount_rub == pytest.approx(1_313.6)
    assert result.broker_commission_rub == pytest.approx(24.5)
    assert result.preview_source == "broker"
    assert result.sufficient_cash is True
    assert result.clean_amount_rub == pytest.approx(1_004.1)


@pytest.mark.asyncio
async def test_preview_pending_operation_falls_back_to_local_when_broker_unavailable() -> None:
    portfolio = _portfolio()
    repo = AsyncMock()
    service = TradingService(repo, sandbox_token="sandbox-token", production_token="prod-token")
    service._sync._ctx.get_trading_portfolio = AsyncMock(return_value=portfolio)  # type: ignore[method-assign]

    with (
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=_snapshot(money_rub=500.0),
        ),
        patch(
            "bond_monitor.application.trading.order_use_case.build_plan",
            return_value=PortfolioPlan(portfolio=portfolio),
        ),
        patch(
            "bond_monitor.application.trading.order_use_case.compute_pending_operations",
            return_value=[_pending_op()],
        ),
        patch(
            "bond_monitor.application.trading.broker.preview_order_price",
            return_value=None,
        ),
    ):
        result = await service.preview_pending_operation(
            portfolio.id,
            "op-1",
            [_bond()],
            key_rate=14.5,
            tax_rate=0.18,
            today=date(2026, 7, 7),
            lots=1,
            price_pct=100.4095,
        )

    assert result.preview_source == "moex"
    assert result.order_lots == 1
    assert result.local_total_amount_rub == pytest.approx(1_289.1, abs=0.02)
    assert result.broker_total_amount_rub is None
    assert result.sufficient_cash is False


def test_preview_endpoint_returns_order_preview_response() -> None:
    with TestClient(app=create_app()) as client, patch(
        "bond_monitor.interfaces.api.controllers.trading.TradingService.preview_pending_operation",
        new_callable=AsyncMock,
        return_value=OrderPreviewResult(
            order_lots=1,
            order_bonds=1,
            lot_size=1,
            order_price_pct=100.4095,
            clean_amount_rub=1_004.1,
            aci_rub_per_bond=285.0,
            local_total_amount_rub=1_289.1,
            broker_clean_amount_rub=1_004.1,
            broker_aci_amount_rub=285.0,
            broker_total_amount_rub=1_313.6,
            broker_commission_rub=24.5,
            money_rub=150_000.0,
            sufficient_cash=True,
            preview_source="broker",
        ),
    ):
        resp = client.post(
            "/api/v1/portfolios/demo/pending-operations/op-1/preview",
            json={"lots": 1, "price_pct": 100.4095},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["order_lots"] == 1
    assert body["order_price_pct"] == pytest.approx(100.4095)
    assert body["broker_total_amount_rub"] == pytest.approx(1_313.6)
    assert body["preview_source"] == "broker"
