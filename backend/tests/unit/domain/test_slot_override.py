"""Tests for reinvestment slot override validation and cascade."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from bond_monitor.domain.portfolio.planner import (
    build_plan,
    clear_downstream_slot_overrides,
    validate_slot_replacement,
)


def _bond(
    *,
    isin: str,
    name: str,
    maturity: date,
    price: float = 99.0,
    ytm: float = 18.0,
    score: float = 80.0,
) -> BondRecord:
    return BondRecord(
        secid=isin[:6],
        isin=isin,
        name=name,
        maturity_date=maturity,
        effective_date=maturity,
        days_to_maturity=max((maturity - date.today()).days, 1),
        last_price=price,
        ytm=ytm,
        ytm_net=ytm * 0.87,
        score=score,
        ytm_score=score,
        risk_score=score,
        liquidity_score=score,
        risk_level=RiskLevel.LOW,
        credit_rating="ruA",
        lot_size=1,
        face_value=1000.0,
        volume_rub=1_000_000,
        api_trade_available_flag=True,
    )


def _position(
    *,
    isin: str,
    name: str,
    maturity: date,
    lots: int = 100,
    purchase_date: date = date(2026, 1, 1),
) -> PortfolioPosition:
    amount = 99.0 * lots
    return PortfolioPosition(
        isin=isin,
        secid=isin[:6],
        name=name,
        lots=lots,
        lot_size=1,
        purchase_clean_price_pct=99.0,
        purchase_dirty_price_rub=99.0,
        purchase_aci_rub=0.0,
        purchase_date=purchase_date,
        purchase_amount_rub=amount,
        coupon_rate=0.10,
        face_value=1000.0,
        maturity_date=maturity,
        offer_date=None,
        coupon_period_days=182,
    )


def test_enrich_reinvestment_slot_includes_candidates_and_status() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 6, 1)
    universe = [
        _bond(isin="RU0001", name="Bond A", maturity=date(2026, 6, 1)),
        _bond(isin="RU0002", name="Bond B", maturity=date(2027, 3, 1)),
        _bond(isin="RU0003", name="Bond C", maturity=date(2027, 5, 1)),
    ]
    portfolio = Portfolio(
        id="p1",
        name="Test",
        initial_amount_rub=400_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.AGGRESSIVE,
        positions=[_position(isin="RU0001", name="Bond A", maturity=date(2026, 6, 1))],
    )
    plan = build_plan(
        portfolio,
        universe,
        today=today,
        key_rate=0.16,
        tax_rate=0.13,
    )
    assert plan.resolved_slots
    slot = plan.resolved_slots[0]
    assert slot.eligible_candidates
    assert slot.selection_mode == "strategy"
    assert slot.status in {"ok", "no_candidate", "invalid_selection", "insufficient_cash"}
    plan_dict = slot.to_plan_dict()
    assert "eligible_candidates" in plan_dict
    assert "selection_mode" in plan_dict
    assert plan_dict["eligible_candidates"][0]["isin"]


def test_validate_slot_replacement_rejects_ineligible() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 6, 1)
    bad_bond = _bond(isin="RU_BAD", name="Too Soon", maturity=date(2026, 3, 1))
    universe = [
        _bond(isin="RU0001", name="Bond A", maturity=date(2026, 6, 1)),
        bad_bond,
        _bond(isin="RU0003", name="Bond C", maturity=date(2027, 5, 1)),
    ]
    portfolio = Portfolio(
        id="p1",
        name="Test",
        initial_amount_rub=400_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.AGGRESSIVE,
        positions=[_position(isin="RU0001", name="Bond A", maturity=date(2026, 6, 1))],
    )
    plan = build_plan(
        portfolio,
        universe,
        today=today,
        key_rate=0.16,
        tax_rate=0.13,
    )
    slot = plan.resolved_slots[0]
    reason = validate_slot_replacement(
        portfolio,
        universe,
        slot=slot,
        confirmed_isin=bad_bond.isin,
        key_rate=0.16,
        tax_rate=0.13,
    )
    assert reason is not None


def test_clear_downstream_slot_overrides() -> None:
    portfolio = Portfolio(
        id="p1",
        name="Test",
        initial_amount_rub=400_000,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.AGGRESSIVE,
        slots=[
            ReinvestmentSlot(
                trigger_date=date(2026, 6, 1),
                trigger_reason=ReinvestmentTriggerReason.MATURITY,
                expected_cash_rub=100_000,
                source_position_isin="RU_SRC1",
                confirmed_isin="RU_MAN1",
            ),
            ReinvestmentSlot(
                trigger_date=date(2027, 3, 1),
                trigger_reason=ReinvestmentTriggerReason.MATURITY,
                expected_cash_rub=100_000,
                source_position_isin="RU_SRC2",
                confirmed_isin="RU_MAN2",
            ),
        ],
    )
    resolved = [
        ReinvestmentSlot(
            trigger_date=date(2026, 6, 1),
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=100_000,
            source_position_isin="RU_SRC1",
            confirmed_isin="RU_MAN1",
        ),
        ReinvestmentSlot(
            trigger_date=date(2027, 3, 1),
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=100_000,
            source_position_isin="RU_SRC2",
            confirmed_isin="RU_MAN2",
        ),
    ]
    changed = clear_downstream_slot_overrides(portfolio, "RU_SRC1", resolved)
    assert changed
    assert portfolio.slots[0].confirmed_isin == "RU_MAN1"
    assert portfolio.slots[1].confirmed_isin is None
