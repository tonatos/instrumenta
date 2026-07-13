"""Application tests for deploy session advice integration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bond_monitor.application.trading.advise_use_case import AdviseUseCase
from bond_monitor.application.trading.context import TradingContext
from bond_monitor.application.trading.deploy_session_use_case import DeploySessionUseCase
from bond_monitor.domain.trading.deploy_session import DeploySession, DeploySessionItem
from bond_monitor.domain.trading.ports import BrokerSnapshot
from bond_monitor.infrastructure.persistence.deploy_session_repository import DeploySessionRepository
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from factories import make_bond, make_portfolio


class _FakeRepo:
    def __init__(self, session: DeploySession) -> None:
        self._session = session

    async def get_active(self, portfolio_id: str) -> DeploySession | None:
        if self._session.portfolio_id == portfolio_id and self._session.status == "active":
            return self._session
        return None

    async def save(self, deploy_session: DeploySession) -> DeploySession:
        self._session = deploy_session
        return deploy_session


@pytest.mark.asyncio
async def test_build_advice_result_persists_active_deploy_session(monkeypatch) -> None:
    portfolio = make_portfolio(initial_amount_rub=100_000.0, horizon_date=date(2028, 1, 1))
    portfolio.id = "pid-1"
    portfolio.mode = "trading"
    portfolio.account_id = "acc-1"
    portfolio.account_kind = "sandbox"

    now = datetime.now(UTC)
    deploy = DeploySession(
        id="sess-1",
        portfolio_id=portfolio.id,
        status="active",
        items=[
            DeploySessionItem(
                id="item-1",
                kind="buy",
                isin="RU000A001",
                name="Bond 1",
                lots=2,
                figi="FIGI-1",
                suggested_price_pct=100.5,
                estimated_amount_rub=20_000.0,
                reason="test",
            )
        ],
        cash_snapshot_rub=80_000.0,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    fake_repo = _FakeRepo(deploy)

    class _Ctx:
        async def get_trading_portfolio(self, portfolio_id: str):
            return portfolio

    deploy_uc = DeploySessionUseCase(_Ctx(), fake_repo)  # type: ignore[arg-type]
    advise_uc = AdviseUseCase(_Ctx(), deploy_uc)  # type: ignore[arg-type]

    bond = make_bond(isin="RU000A001", figi="FIGI-1", price=100.0)
    snapshot = BrokerSnapshot(
        account_id="acc-1",
        account_kind="sandbox",
        money_rub=80_000.0,
        blocked_money_rub=0.0,
        bond_positions={},
        other_instruments=[],
        fetched_at=now.isoformat(),
    )

    result = await advise_uc.build_advice_result(
        portfolio,
        [bond],
        snapshot=snapshot,
        operations=[],
        active_orders=[],
        key_rate=16.0,
        tax_rate=0.13,
        today=date.today(),
    )

    assert result.deploy_session is not None
    assert result.deploy_session.id == "sess-1"
    buy = [s for s in result.suggestions if s.kind == "buy"]
    assert len(buy) == 1
    assert buy[0].isin == "RU000A001"
