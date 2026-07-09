"""Unit tests for unified bond selection."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.portfolio.policies import BondSelectionContext
from bond_monitor.domain.portfolio.selection import (
    MaturityIndex,
    SelectionOptions,
    bond_eligibility_reason,
    eligible_bonds,
    explain_selection_failure,
    rank_bonds,
    select_best_bond,
    select_ranked_bonds,
)


def _bond(
    *,
    isin: str,
    name: str,
    maturity: date,
    price: float = 99.0,
    ytm: float = 20.0,
    score: float = 80.0,
    rating: str | None = "ruA",
    risk: RiskLevel = RiskLevel.LOW,
    api_trade: bool = True,
) -> BondRecord:
    bond = BondRecord(
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
        risk_level=risk,
        credit_rating=rating,
        lot_size=1,
        face_value=1000.0,
        volume_rub=1_000_000,
        api_trade_available_flag=api_trade,
    )
    bond.accrued_interest = 0.0
    return bond


def _ctx(
    *,
    purchase_date: date = date(2026, 7, 7),
    horizon: date = date(2027, 7, 7),
    profile: RiskProfile = RiskProfile.AGGRESSIVE,
    budget: float | None = None,
) -> BondSelectionContext:
    return BondSelectionContext(
        profile=profile,
        horizon_date=horizon,
        purchase_date=purchase_date,
        budget_rub=budget,
        api_trade_only=True,
    )


def test_eligibility_rejects_clean_below_threshold() -> None:
    distressed = _bond(
        isin="RU000A10BB75",
        name="ЕвроТранс7",
        maturity=date(2027, 3, 31),
        price=75.0,
        rating=None,
        risk=RiskLevel.HIGH,
    )
    reason = bond_eligibility_reason(distressed, _ctx())
    assert reason is not None
    assert "85" in reason


def test_maturity_window_requires_min_horizon() -> None:
    short = _bond(
        isin="RU000A100PB0",
        name="ЖКХРСЯ БО1",
        maturity=date(2026, 7, 15),
        price=99.0,
    )
    ctx = _ctx(purchase_date=date(2026, 7, 7))
    reason = bond_eligibility_reason(short, ctx)
    assert reason is not None
    assert "раньше окна" in reason


def test_normal_profile_filter_is_stricter_than_aggressive() -> None:
    junk = _bond(
        isin="RU000A1",
        name="Junk",
        maturity=date(2027, 6, 1),
        price=95.0,
        rating="ruBB",
        risk=RiskLevel.HIGH,
    )
    quality = _bond(
        isin="RU000A2",
        name="Quality",
        maturity=date(2027, 6, 1),
        price=98.0,
        rating="ruA",
        risk=RiskLevel.LOW,
    )
    ctx = _ctx(profile=RiskProfile.AGGRESSIVE)
    aggressive_eligible = {
        b.isin
        for b in eligible_bonds(
            [junk, quality], ctx, profile_step=RiskProfile.AGGRESSIVE
        )
    }
    normal_eligible = {
        b.isin for b in eligible_bonds([junk, quality], ctx, profile_step=RiskProfile.NORMAL)
    }
    assert aggressive_eligible == {"RU000A1", "RU000A2"}
    assert normal_eligible == {"RU000A2"}


def test_fallback_chain_picks_no_profile_when_rated_profiles_empty() -> None:
    unrated = _bond(
        isin="RU000A3",
        name="NoRating",
        maturity=date(2027, 6, 1),
        price=96.0,
        rating=None,
        risk=RiskLevel.MODERATE,
    )
    ctx = _ctx(profile=RiskProfile.NORMAL)
    result = select_ranked_bonds(
        [unrated],
        ctx,
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert result.bonds
    assert result.bonds[0].isin == "RU000A3"
    assert result.effective_profile_filter is None
    assert "без профильных ограничений" in result.fallback_note


def test_fallback_chain_picks_normal_when_aggressive_empty() -> None:
    """When aggressive pool is empty, normal-eligible bonds are ranked."""
    quality = _bond(
        isin="RU000A2",
        name="Quality",
        maturity=date(2027, 6, 1),
        price=98.0,
        rating="ruA",
        risk=RiskLevel.LOW,
    )
    ctx = _ctx(profile=RiskProfile.AGGRESSIVE)
    result = select_ranked_bonds(
        [quality],
        ctx,
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert result.bonds[0].isin == "RU000A2"
    assert result.effective_profile_filter == RiskProfile.AGGRESSIVE
    assert result.fallback_note == ""


def test_ranking_uses_portfolio_profile_weights_even_on_fallback() -> None:
    low_ytm = _bond(
        isin="RU000A4",
        name="LowYtm",
        maturity=date(2027, 6, 1),
        price=99.0,
        ytm=15.0,
        score=50.0,
        rating="ruA",
    )
    high_ytm = _bond(
        isin="RU000A5",
        name="HighYtm",
        maturity=date(2027, 6, 1),
        price=95.0,
        ytm=35.0,
        score=90.0,
        rating="ruA",
    )
    ctx = _ctx(profile=RiskProfile.AGGRESSIVE)
    ranked = rank_bonds([low_ytm, high_ytm], ctx.profile, key_rate=16.0, tax_rate=0.13)
    assert ranked[0].isin == "RU000A5"


def test_select_best_bond_respects_budget() -> None:
    pricey = _bond(
        isin="RU000A6",
        name="Pricey",
        maturity=date(2027, 6, 1),
        price=99.0,
    )
    ctx = _ctx(budget=500.0)
    bond, reason = select_best_bond(
        [pricey],
        ctx,
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert bond is None
    assert "мин. лот" in reason


def test_explain_selection_failure_narrow_window() -> None:
    ctx = _ctx(
        purchase_date=date(2027, 7, 6),
        horizon=date(2027, 7, 15),
    )
    reason = explain_selection_failure([], ctx)
    assert "окно реинвестиции слишком узкое" in reason
    assert "16 июля 2027" in reason


def test_eligible_bonds_unified_for_compose_and_reinvest() -> None:
    ok = _bond(isin="RU000A7", name="Ok", maturity=date(2027, 6, 1), price=90.0)
    distressed = _bond(
        isin="RU000A8",
        name="Distressed",
        maturity=date(2027, 6, 1),
        price=70.0,
        rating=None,
        risk=RiskLevel.HIGH,
    )
    ctx = _ctx()
    eligible = eligible_bonds([ok, distressed], ctx, profile_step=RiskProfile.AGGRESSIVE)
    assert [b.isin for b in eligible] == ["RU000A7"]


def test_maturity_index_limits_window_scan() -> None:
    in_window = _bond(isin="RU000A9", name="In", maturity=date(2027, 6, 1))
    out_window = _bond(isin="RU000A10", name="Out", maturity=date(2035, 1, 1))
    ctx = _ctx()
    index = MaturityIndex.build([in_window, out_window])
    narrowed = index.bonds_between(date(2026, 1, 1), date(2028, 1, 1))
    assert [b.isin for b in narrowed] == ["RU000A9"]
    eligible = eligible_bonds(
        [in_window, out_window],
        ctx,
        profile_step=RiskProfile.NORMAL,
        selection_options=SelectionOptions(maturity_index=index),
    )
    assert [b.isin for b in eligible] == ["RU000A9"]
