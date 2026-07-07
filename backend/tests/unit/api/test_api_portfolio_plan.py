"""Plan API must expose computed reinvestment slots, not only cashflow."""

from __future__ import annotations

from litestar.testing import TestClient

from conftest import portfolio_client


def test_get_plan_includes_resolved_slots() -> None:
    with portfolio_client(
        "Plan Slots Test",
        initial_amount_rub=400_000.0,
        horizon_date="2027-06-01",
        risk_profile="aggressive",
    ) as (client, pid):
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
            assert "selection_mode" in slot
            assert "status" in slot
            assert "eligible_candidates" in slot
            assert isinstance(slot["eligible_candidates"], list)


def test_set_slot_override_rejects_ineligible_bond() -> None:
    with portfolio_client(
        "Plan Slots Test",
        initial_amount_rub=400_000.0,
        horizon_date="2027-06-01",
        risk_profile="aggressive",
    ) as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        plan = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        if not plan["slots"]:
            return

        slot = next(
            (s for s in plan["slots"] if s.get("source_position_isin")),
            None,
        )
        if slot is None:
            return

        source_isin = slot["source_position_isin"]

        resp = client.post(
            f"/api/v1/portfolios/{pid}/slots/override",
            json={"source_position_isin": source_isin, "confirmed_isin": source_isin},
        )
        assert resp.status_code == 422, resp.text


def test_horizon_change_rebuilds_plan_slots_without_touching_positions() -> None:
    with portfolio_client(name="Horizon Change") as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        before = client.get(f"/api/v1/portfolios/{pid}").json()
        plan_short = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        short_slots = len(plan_short["slots"])

        resp = client.patch(
            f"/api/v1/portfolios/{pid}",
            json={"horizon_date": "2028-06-01"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["horizon_date"] == "2028-06-01"

        after = client.get(f"/api/v1/portfolios/{pid}").json()
        assert after["data"]["positions"] == before["data"]["positions"]

        plan_long = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        assert len(plan_long["slots"]) >= short_slots


def test_reset_all_slot_overrides() -> None:
    with portfolio_client(
        "Plan Slots Test",
        initial_amount_rub=400_000.0,
        horizon_date="2027-06-01",
        risk_profile="aggressive",
    ) as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        plan = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        if not plan["slots"]:
            return

        slot = plan["slots"][0]
        source_isin = slot["source_position_isin"]
        override_isin = slot.get("suggested_isin")
        if not source_isin or not override_isin:
            return

        client.post(
            f"/api/v1/portfolios/{pid}/slots/override",
            json={"source_position_isin": source_isin, "confirmed_isin": override_isin},
        )

        resp = client.post(f"/api/v1/portfolios/{pid}/slots/reset-all")
        assert resp.status_code == 200, resp.text

        plan_after = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        matched = [
            s for s in plan_after["slots"] if s["source_position_isin"] == source_isin
        ]
        if matched:
            assert matched[0]["confirmed_isin"] is None
            assert matched[0]["selection_mode"] == "strategy"


def test_set_slot_override_by_source_position_isin() -> None:
    with portfolio_client(
        "Plan Slots Test",
        initial_amount_rub=400_000.0,
        horizon_date="2027-06-01",
        risk_profile="aggressive",
    ) as (client, pid):
        client.post(f"/api/v1/portfolios/{pid}/auto-compose")
        plan = client.get(f"/api/v1/portfolios/{pid}/plan").json()
        if not plan["slots"]:
            return

        slot = next(
            (s for s in plan["slots"] if s.get("source_position_isin")),
            None,
        )
        if slot is None:
            return

        source_isin = slot["source_position_isin"]
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
