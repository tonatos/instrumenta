"""Tests for reusing portfolio plan during trading sync."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.domain.portfolio.models import AccountKind, Portfolio, RiskProfile
from bond_monitor.domain.portfolio.planner import PortfolioPlan
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot


def _portfolio() -> Portfolio:
    return Portfolio(
        name="Reuse Plan",
        initial_amount_rub=100_000.0,
        horizon_date=date(2027, 1, 1),
        risk_profile=RiskProfile.NORMAL,
        mode="trading",  # type: ignore[arg-type]
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
    )


def _snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        account_id="acc-1",
        account_kind=AccountKind.SANDBOX,
        money_rub=Rub(100_000.0),
        bond_positions={},
        other_instruments=[],
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@pytest.mark.asyncio
async def test_sync_portfolio_reuses_plan_when_provided() -> None:
    portfolio = _portfolio()
    reused_plan = PortfolioPlan(portfolio=portfolio)
    repo = AsyncMock()
    repo.save = AsyncMock(return_value=portfolio)
    service = TradingService(repo, sandbox_token="sandbox-token", production_token="prod-token")
    service._get_trading_portfolio = AsyncMock(return_value=portfolio)  # type: ignore[method-assign]

    with (
        patch(
            "bond_monitor.application.trading.trading_service.get_account_snapshot",
            return_value=_snapshot(),
        ),
        patch(
            "bond_monitor.application.trading.trading_service.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.trading_service.build_plan",
        ) as build_plan_mock,
        patch(
            "bond_monitor.application.trading.trading_service.compute_pending_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.trading_service._block_non_api_tradable_pending",
        ),
        patch(
            "bond_monitor.application.trading.trading_service.detect_top_up",
            return_value=MagicMock(has_pending_top_up=False, pending_top_up_rub=Rub(0)),
        ),
    ):
        result = await service.sync_portfolio(
            portfolio.id,
            [],
            key_rate=14.5,
            tax_rate=0.18,
            today=date.today(),
            reuse_plan=reused_plan,
        )

    build_plan_mock.assert_not_called()
    assert result.pending_operations == []
