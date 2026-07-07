"""Plan API must expose computed reinvestment slots, not only cashflow."""

from __future__ import annotations

import contextlib
from collections.abc import Generator

from litestar.testing import TestClient

from bond_monitor.main import create_app


@contextlib.contextmanager
def _portfolio_client(name: str = "Plan Slots Test") -> Generator[tuple[TestClient, str], None, None]:
    with TestClient(app=create_app()) as client:
        resp = client.post(
            "/api/v1/portfolios/",
            json={
                "name": name,
                "initial_amount_rub": 400_000.0,
                "horizon_date": "2027-06-01",
                "risk_profile": "aggressive",
            },
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        try:
            yield client, pid
        finally:
            client.delete(f"/api/v1/portfolios/{pid}")


def test_get_plan_includes_resolved_slots() -> None:
    with _portfolio_client() as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")

        resp = client.get(f"/api/v1/portfolios/{pid}/plan")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert "slots" in body
        assert isinstance(body["slots"], list)
        assert "value_timeline" in body
        assert isinstance(body["value_timeline"], list)
        if body["value_timeline"]:
            point = body["value_timeline"][0]
            assert "date" in point
            assert "cash_rub" in point
            assert "positions_value_rub" in point
            assert "total_value_rub" in point

        reinvest_purchases = [
            e for e in body["cashflow"] if e["kind"] == "purchase" and "Покупка" in e.get("label", "")
        ]
        if reinvest_purchases:
            assert len(body["slots"]) > 0, "cashflow has reinvest purchases but plan.slots is empty"
            slot = body["slots"][0]
            assert "trigger_date" in slot
            assert "trigger_reason" in slot
            assert "expected_cash_rub" in slot
            assert "source_position_isin" in slot


def test_set_slot_override_by_source_position_isin() -> None:
    with _portfolio_client() as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        plan = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        if not plan["slots"]:
            return

        slot = plan["slots"][0]
        source_isin = slot["source_position_isin"]
        assert source_isin
        # Use suggested replacement — reinvesting into the maturing bond is rejected by planner.
        override_isin = slot.get("suggested_isin")
        if not override_isin:
            return

        resp = client.post(
            f"/api/v1/portfolios/{pid}/slots/override",
            json={"source_position_isin": source_isin, "confirmed_isin": override_isin},
        )
        assert resp.status_code == 200, resp.text

        plan_after = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        matched = [
            s for s in plan_after["slots"] if s["source_position_isin"] == source_isin
        ]
        assert matched
        assert matched[0]["confirmed_isin"] == override_isin
