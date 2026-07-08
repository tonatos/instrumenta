"""Shared pytest fixtures for bond-monitor tests."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from litestar.testing import TestClient

from bond_monitor.main import create_app

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from factories import make_account_snapshot, portfolio_create_payload  # noqa: E402
from bond_monitor.interfaces.auth.jwt_auth import reset_jwt_auth_cache  # noqa: E402
from bond_monitor.interfaces.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _auth_disabled_for_tests(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("AUTH_DISABLED", "true")
    get_settings.cache_clear()
    reset_jwt_auth_cache()
    yield
    get_settings.cache_clear()
    reset_jwt_auth_cache()


@contextlib.contextmanager
def linked_trading_account(
    *,
    linked_name: str = "Уже в торговле",
    account_id: str = "acc-linked",
    money_rub: float = 150_000.0,
    figi: str = "FIGI123",
    auto_compose: bool = False,
) -> Generator[tuple[TestClient, str, str], None, None]:
    """Portfolio with account already in TRADING mode; yields (client, pid, account_id)."""
    with portfolio_client(linked_name) as (client, pid):
        snapshot = make_account_snapshot(money_rub, account_id=account_id)
        with (
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
                return_value=figi,
            ),
        ):
            if auto_compose:
                client.post(f"/api/v1/portfolios/{pid}/auto-compose")
            resp = client.post(
                f"/api/v1/portfolios/{pid}/attach",
                json={"account_id": account_id, "kind": "sandbox"},
            )
            assert resp.status_code == 201, resp.text
            yield client, pid, account_id


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app=create_app()) as test_client:
        yield test_client


@contextlib.contextmanager
def portfolio_client(
    name: str = "Test Portfolio",
    *,
    initial_amount_rub: float = 100_000.0,
    horizon_date: str = "2027-01-01",
    risk_profile: str = "normal",
) -> Generator[tuple[TestClient, str], None, None]:
    with TestClient(app=create_app()) as test_client:
        resp = test_client.post(
            "/api/v1/portfolios/",
            json=portfolio_create_payload(
                name,
                initial_amount_rub=initial_amount_rub,
                horizon_date=horizon_date,
                risk_profile=risk_profile,
            ),
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        try:
            yield test_client, pid
        finally:
            test_client.delete(f"/api/v1/portfolios/{pid}")


def attach_trading_portfolio(
    client: TestClient,
    pid: str,
    *,
    account_id: str = "acc-clean",
    money_rub: float = 150_000.0,
    figi: str = "FIGI123",
    auto_compose: bool = True,
) -> None:
    snapshot = make_account_snapshot(money_rub, account_id=account_id)
    with (
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
            return_value=figi,
        ),
    ):
        if auto_compose:
            client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        resp = client.post(
            f"/api/v1/portfolios/{pid}/attach",
            json={"account_id": account_id, "kind": "sandbox"},
        )
        assert resp.status_code == 201, resp.text
