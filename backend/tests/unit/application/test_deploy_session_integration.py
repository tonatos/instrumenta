"""Integration test for deploy session + advice with real SQLite repo."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.application.trading.trading_service import TradingService
from bond_monitor.infrastructure.persistence.database import get_session_factory, init_db
from bond_monitor.infrastructure.persistence.deploy_session_repository import DeploySessionRepository
from bond_monitor.infrastructure.persistence.repository import PortfolioRepository
from bond_monitor.interfaces.config import get_settings
from bond_monitor.domain.portfolio.models import PortfolioMode
from bond_monitor.domain.trading.models import AccountKind
from factories import make_account_snapshot, make_bond, portfolio_create_payload


@pytest.mark.asyncio
async def test_get_advice_after_deploy_session_persisted() -> None:
    await init_db()
    settings = get_settings()
    bonds = [
        make_bond(
            isin=f"RU000A{i:03d}",
            figi=f"FIGI-{i}",
            price=100.0,
            ytm=18.0 + i,
            score=80.0 + i,
            maturity=date(2026, 12, 1),
        )
        for i in range(8)
    ]
    universe = type("U", (), {"bonds": bonds})()

    factory = get_session_factory()
    async with factory() as db:
        portfolio_repo = PortfolioRepository(db)
        deploy_repo = DeploySessionRepository(db)
        svc = TradingService(
            portfolio_repo,
            deploy_repo,
            sandbox_token=settings.t_trading_token_sandbox,
            production_token=settings.t_trading_token_production,
        )

        from litestar.testing import TestClient
        from bond_monitor.main import create_app

        with TestClient(app=create_app()) as client:
            pid = client.post(
                "/api/v1/portfolios/",
                json=portfolio_create_payload("Repo flow"),
            ).json()["id"]

        portfolio = await portfolio_repo.get_by_id(pid)
        assert portfolio is not None
        portfolio.mode = PortfolioMode.TRADING
        portfolio.account_id = "acc-repo-flow"
        portfolio.account_kind = AccountKind.SANDBOX
        await portfolio_repo.save(portfolio)

        with (
            patch.object(BondService, "load_universe", return_value=universe),
            patch(
                "bond_monitor.application.trading.broker.get_account_snapshot",
                return_value=make_account_snapshot(80_000.0, account_id="acc-repo-flow"),
            ),
            patch(
                "bond_monitor.application.trading.broker.get_account_operations",
                return_value=[],
            ),
            patch(
                "bond_monitor.application.trading.broker.get_active_orders",
                return_value=[],
            ),
        ):
            created = await svc.create_deploy_session(
                pid,
                bonds,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
            )
            assert created.items

            result = await svc.get_advice(
                pid,
                bonds,
                key_rate=settings.key_rate,
                tax_rate=settings.tax_rate_fraction,
                today=date.today(),
            )

        assert result.deploy_session is not None
        assert result.deploy_session.status == "active"
