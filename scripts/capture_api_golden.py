#!/usr/bin/env python3
"""Capture golden API JSON snapshots from the Python Litestar backend.

Run from repo root:
  uv run --directory backend python ../scripts/capture_api_golden.py

Output: backend/testdata/golden/*.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure backend tests + src are importable
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
TESTS_DIR = BACKEND_DIR / "tests"
sys.path.insert(0, str(BACKEND_DIR / "src"))
sys.path.insert(0, str(TESTS_DIR))

os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{REPO_ROOT / 'cache' / 'golden_capture.db'}")

from litestar.testing import TestClient  # noqa: E402

from bond_monitor.application.bonds.bond_service import BondLoadResult, BondService  # noqa: E402
from bond_monitor.interfaces.auth.jwt_auth import reset_jwt_auth_cache  # noqa: E402
from bond_monitor.interfaces.config import get_settings  # noqa: E402
from bond_monitor.main import create_app  # noqa: E402
from conftest import attach_trading_portfolio  # noqa: E402
from factories import (  # noqa: E402
    aa19dfd_portfolio,
    aa19dfd_universe,
    make_account_snapshot,
    make_bond,
    portfolio_create_payload,
)

GOLDEN_DIR = BACKEND_DIR / "testdata" / "golden"

# Fields replaced with stable placeholders during normalization
VOLATILE_KEY_PATTERNS = re.compile(
    r"^(id|created_at|updated_at|as_of|fetched_at|expires_at|completed_at|request_uid|order_id)$"
)
UUID_LIKE = re.compile(
    r"^[0-9a-f]{8}[0-9a-f]{4}[0-9a-f]{4}[0-9a-f]{4}[0-9a-f]{12}$", re.I
)


def normalize_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return normalize_obj(value)
    if isinstance(value, list):
        return [normalize_item(i, v) for i, v in enumerate(value)]
    if isinstance(value, str):
        if VOLATILE_KEY_PATTERNS.match(key) or UUID_LIKE.match(value):
            if key in ("id", "order_id", "request_uid"):
                return "<ID>"
            if key in ("created_at", "updated_at", "as_of", "fetched_at", "expires_at", "completed_at"):
                return "<TIMESTAMP>"
        return value
    if isinstance(value, float):
        return round(value, 6)
    return value


def normalize_item(_index: int, value: Any) -> Any:
    if isinstance(value, dict):
        return normalize_obj(value)
    if isinstance(value, list):
        return [normalize_item(i, v) for i, v in enumerate(value)]
    if isinstance(value, float):
        return round(value, 6)
    return value


def normalize_obj(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: normalize_value(k, v) for k, v in sorted(obj.items())}


def save_golden(name: str, payload: dict[str, Any], *, status: int = 200) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "status": status,
        "body": normalize_obj(payload) if isinstance(payload, dict) else payload,
    }
    path = GOLDEN_DIR / f"{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(REPO_ROOT)}")


def _screener_result(bonds: list | None = None) -> BondLoadResult:
    items = bonds if bonds is not None else aa19dfd_universe()
    return BondLoadResult(bonds=items, source="golden-mock")


def _universe():
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
    return BondLoadResult(bonds=bonds, source="golden-mock")


def _mock_bond_service(bonds: list | None = None) -> MagicMock:
    items = bonds if bonds is not None else aa19dfd_universe()
    from bond_monitor.domain.screening.scorer import score_bonds_all_profiles

    scored = score_bonds_all_profiles(items, key_rate=14.5, tax_rate=0.13)
    svc = MagicMock(spec=BondService)
    svc.load_screener_bonds.return_value = BondLoadResult(bonds=scored, source="golden-mock")
    svc.load_universe.return_value = BondLoadResult(bonds=scored, source="golden-mock")
    svc.load_by_secid.side_effect = lambda secid, **kw: next((b for b in scored if b.secid == secid), None)
    svc.load_by_isins.return_value = BondLoadResult(bonds=scored, source="golden-mock")
    return svc


@contextmanager
def bond_service_patch(bonds: list | None = None):
    mock_svc = _mock_bond_service(bonds)
    with patch(
        "bond_monitor.interfaces.api.controllers.bonds.provide_bond_service",
        return_value=mock_svc,
    ), patch(
        "bond_monitor.interfaces.api.controllers.portfolio.provide_bond_service",
        return_value=mock_svc,
    ), patch(
        "bond_monitor.interfaces.api.controllers.trading.provide_bond_service",
        return_value=mock_svc,
    ):
        yield mock_svc


@contextmanager
def trading_patches(money_rub: float = 500_000.0):
    with (
        bond_service_patch(),
        patch(
            "bond_monitor.application.trading.broker.get_account_snapshot",
            return_value=make_account_snapshot(money_rub),
        ),
        patch(
            "bond_monitor.application.trading.broker.get_account_operations",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.get_active_orders",
            return_value=[],
        ),
        patch(
            "bond_monitor.application.trading.broker.resolve_figi_for_isin",
            return_value="FIGI-TEST",
        ),
    ):
        yield


def capture() -> None:
    get_settings.cache_clear()
    reset_jwt_auth_cache()

    with TestClient(app=create_app()) as client:
        # Config
        resp = client.get("/api/v1/config/")
        assert resp.status_code == 200, resp.text
        save_golden("config_get", resp.json())

        # Health
        resp = client.get("/health")
        assert resp.status_code == 200
        save_golden("health_get", resp.json())

        # Bonds list
        with bond_service_patch():
            resp = client.get("/api/v1/bonds/?risk_profile=normal&rate_scenario=hold")
        assert resp.status_code == 200, resp.text
        save_golden("bonds_list_normal_hold", resp.json())

        # Portfolio CRUD
        resp = client.post(
            "/api/v1/portfolios/",
            json=portfolio_create_payload("Golden Portfolio"),
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        save_golden("portfolio_create", resp.json())

        resp = client.get("/api/v1/portfolios/")
        assert resp.status_code == 200
        save_golden("portfolios_list", {"portfolios": resp.json()})

        resp = client.get(f"/api/v1/portfolios/{pid}")
        assert resp.status_code == 200
        save_golden("portfolio_get", resp.json())

        with bond_service_patch():
            resp = client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        assert resp.status_code in (200, 201), resp.text
        save_golden("portfolio_auto_compose", resp.json())

        with bond_service_patch():
            resp = client.get(f"/api/v1/portfolios/{pid}/plan")
        assert resp.status_code == 200, resp.text
        save_golden("portfolio_plan", resp.json())

        # Trading attach + state
        attach_trading_portfolio(
            client, pid, money_rub=80_000.0, auto_compose=False, account_id=f"acc-golden-{pid[:8]}"
        )
        with trading_patches(80_000.0):
            resp = client.get(f"/api/v1/portfolios/{pid}/trading-state")
        assert resp.status_code == 200, resp.text
        save_golden("trading_state", resp.json())

        with trading_patches(80_000.0):
            resp = client.get(f"/api/v1/portfolios/{pid}/advice")
        assert resp.status_code == 200, resp.text
        save_golden("advice", resp.json())

        # Deploy session
        with trading_patches(80_000.0):
            resp = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
        assert resp.status_code == 201, resp.text
        session = resp.json()
        save_golden("deploy_session_create", session)

        with trading_patches(80_000.0):
            resp = client.get(f"/api/v1/portfolios/{pid}/deploy-sessions/active")
        assert resp.status_code == 200
        save_golden("deploy_session_active", resp.json())

        with trading_patches(80_000.0):
            resp = client.post(f"/api/v1/portfolios/{pid}/deploy-sessions")
        assert resp.status_code == 409
        save_golden("deploy_session_conflict", resp.json(), status=409)

        # Order preview
        with trading_patches(80_000.0):
            with patch(
                "bond_monitor.application.trading.broker.preview_order_price",
                return_value=None,
            ):
                resp = client.post(
                    f"/api/v1/portfolios/{pid}/orders/preview",
                    json={
                        "isin": "RU000A000",
                        "direction": "BUY",
                        "lots": 1,
                        "price_pct": 100.0,
                    },
                )
            if resp.status_code == 200:
                save_golden("order_preview_buy", resp.json())

        # Slots override 422
        sim_pid_resp = client.post(
            "/api/v1/portfolios/",
            json=portfolio_create_payload("Slots Test", initial_amount_rub=50_000.0),
        )
        sim_pid = sim_pid_resp.json()["id"]
        with bond_service_patch():
            client.post(f"/api/v1/portfolios/{sim_pid}/auto-compose")
        portfolio = client.get(f"/api/v1/portfolios/{sim_pid}").json()
        slots = portfolio.get("data", {}).get("slots", [])
        if len(slots) >= 1:
            source_isin = slots[0].get("source_position_isin") or slots[0].get("confirmed_isin")
            resp = client.post(
                f"/api/v1/portfolios/{sim_pid}/slots/override",
                json={"source_position_isin": source_isin, "confirmed_isin": source_isin},
            )
            assert resp.status_code == 422, resp.text
            save_golden("slots_override_invalid", resp.json(), status=422)

        # Favorites
        resp = client.get("/api/v1/favorites/")
        assert resp.status_code == 200
        save_golden("favorites_list", resp.json())

        # Notifications
        resp = client.get(f"/api/v1/portfolios/{pid}/notifications")
        assert resp.status_code == 200
        save_golden("notifications_list", resp.json())

        # Calculator
        with bond_service_patch():
            resp = client.post(
                "/api/v1/calculator/portfolio",
                json={
                    "secids": ["RU000A100PB0", "RU000A109TG2"],
                    "budget_rub": 100_000.0,
                },
            )
        assert resp.status_code in (200, 201), resp.text
        save_golden("calculator_portfolio", resp.json())

        # 404
        resp = client.get("/api/v1/portfolios/nonexistent-id/trading-state")
        assert resp.status_code == 404
        save_golden("trading_state_not_found", resp.json(), status=404)

        # Cleanup
        client.delete(f"/api/v1/portfolios/{pid}")
        client.delete(f"/api/v1/portfolios/{sim_pid}")

    # Save aa19dfd domain fixture reference
    save_golden("aa19dfd_portfolio_meta", {"name": aa19dfd_portfolio().name, "positions": len(aa19dfd_portfolio().positions)})


if __name__ == "__main__":
    print("Capturing golden API snapshots...")
    capture()
    print("Done.")
