"""Duration business scenarios: metric, guardrail, rate-scenario ranking.

Проверяем бизнес-поведение (риск-контур и duration-play), а не синтетику:
дюрация видна в плане, гардрейл ограничивает процентный риск, а сценарий
по ставке разворачивает предпочтение между длинными и короткими бумагами.
"""

from __future__ import annotations

from datetime import date

import pytest

from factories import make_bond

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    RiskProfile,
)
from bond_monitor.domain.portfolio.planner import auto_compose, build_plan
from bond_monitor.domain.portfolio.policies import (
    DurationPolicy,
    RateScenario,
    resolve_duration_policy,
)
from bond_monitor.domain.portfolio.duration_metrics import weighted_duration_by_market
from bond_monitor.domain.screening.scorer import (
    calc_target_duration_adjustment,
    score_bonds_for_profile,
)
from bond_monitor.domain.trading.advisory import HoldingView


def test_duration_years_uses_moex_then_proxy() -> None:
    """MOEX-дюрация приоритетна; без неё — прокси из срока до погашения."""
    moex = make_bond(isin="RU000MOEX", duration_days=365, days_to_maturity=500)
    assert moex.duration_years == 1.0
    assert moex.duration_is_proxy is False

    proxy = make_bond(isin="RU000PRXY", duration_days=None, days_to_maturity=730)
    assert proxy.duration_years == 2.0
    assert proxy.duration_is_proxy is True

    empty = make_bond(isin="RU000NONE", duration_days=None, days_to_maturity=None)
    assert empty.duration_years is None
    assert empty.duration_is_proxy is False


def test_plan_reports_weighted_duration() -> None:
    """План показывает средневзвешенную дюрацию текущих позиций (годы)."""
    today = date(2026, 1, 1)
    horizon = date(2027, 6, 1)
    bond = make_bond(
        isin="RU000DUR1",
        name="Dur bond",
        maturity=date(2027, 3, 1),
        duration_days=365,
    )
    portfolio = Portfolio(
        id="dur",
        name="Dur",
        initial_amount_rub=100_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.NORMAL,
        positions=[
            PortfolioPosition(
                isin=bond.isin,
                secid=bond.secid,
                name=bond.name,
                lots=10,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=99_000,
                maturity_date=bond.maturity_date,
                offer_date=None,
                coupon_rate=12.0,
                coupon_period_days=182,
                next_coupon_date=date(2026, 7, 1),
            )
        ],
    )
    plan = build_plan(portfolio, [bond], today=today, key_rate=14.5, tax_rate=0.13)
    assert plan.weighted_duration_years == 1.0


def test_duration_guardrail_excludes_long_bonds() -> None:
    """Гардрейл: при лимите дюрации длинные бумаги не попадают в корзину."""
    today = date(2026, 1, 1)
    horizon = date(2029, 1, 1)
    short = make_bond(
        isin="RU000SHORT",
        name="Short",
        maturity=date(2027, 1, 1),
        duration_days=365,
    )
    long = make_bond(
        isin="RU000LONG",
        name="Long",
        maturity=date(2028, 12, 1),
        duration_days=1095,
        score=99.0,  # выше по скору, но должен быть отсечён гардрейлом
    )

    positions, _cash, notes = auto_compose(
        initial_amount=200_000,
        universe=[short, long],
        profile=RiskProfile.NORMAL,
        horizon_date=horizon,
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        api_trade_only=False,
        duration_policy=DurationPolicy(max_weighted_duration_years=2.0),
    )
    assert positions
    assert all(p.isin != long.isin for p in positions)
    assert any("Гардрейл по дюрации" in n for n in notes)


def _two_bonds_same_except_duration() -> tuple:
    short = make_bond(
        isin="RU000S",
        name="Short",
        maturity=date(2027, 1, 1),
        duration_days=200,
    )
    long = make_bond(
        isin="RU000L",
        name="Long",
        maturity=date(2027, 1, 1),
        duration_days=1000,
    )
    return short, long


def test_rate_scenario_flips_duration_preference() -> None:
    """CUT поднимает длинную бумагу, HIKE — короткую (при равных YTM/risk/liq)."""
    short, long = _two_bonds_same_except_duration()

    cut = score_bonds_for_profile(
        [short, long],
        RiskProfile.NORMAL,
        key_rate=14.5,
        tax_rate=0.13,
        duration_policy=DurationPolicy(
            duration_score_weight=0.2, rate_scenario=RateScenario.CUT
        ),
    )
    assert cut[0].isin == "RU000L"

    hike = score_bonds_for_profile(
        [short, long],
        RiskProfile.NORMAL,
        key_rate=14.5,
        tax_rate=0.13,
        duration_policy=DurationPolicy(
            duration_score_weight=0.2, rate_scenario=RateScenario.HIKE
        ),
    )
    assert hike[0].isin == "RU000S"


def test_default_duration_policy_is_noop() -> None:
    """С дефолтной политикой дюрация не влияет на скор (обратная совместимость)."""
    short, long = _two_bonds_same_except_duration()
    scored = score_bonds_for_profile(
        [short, long],
        RiskProfile.NORMAL,
        key_rate=14.5,
        tax_rate=0.13,
    )
    by_isin = {b.isin: b.score for b in scored}
    assert by_isin["RU000S"] == by_isin["RU000L"]


def test_resolve_duration_policy_hold_is_noop() -> None:
    policy = resolve_duration_policy(rate_scenario=RateScenario.HOLD)
    assert policy.duration_score_weight == 0.0
    assert policy.target_duration_years is None


def test_resolve_duration_policy_cut_and_hike_defaults() -> None:
    cut = resolve_duration_policy(rate_scenario=RateScenario.CUT)
    assert cut.duration_score_weight == 0.20
    assert cut.target_duration_years == 2.0

    hike = resolve_duration_policy(rate_scenario=RateScenario.HIKE)
    assert hike.duration_score_weight == 0.20
    assert hike.target_duration_years == 0.5


def test_resolve_duration_policy_portfolio_overrides_target() -> None:
    policy = resolve_duration_policy(
        rate_scenario=RateScenario.CUT,
        max_weighted_duration_years=3.0,
        target_duration_years=1.5,
    )
    assert policy.max_weighted_duration_years == 3.0
    assert policy.target_duration_years == 1.5


def test_calc_target_duration_adjustment_prefers_closer_bond() -> None:
    near = calc_target_duration_adjustment(
        2.0,
        target_years=2.0,
        scale_years=4.0,
        weight=0.2,
    )
    far = calc_target_duration_adjustment(
        0.5,
        target_years=2.0,
        scale_years=4.0,
        weight=0.2,
    )
    assert near > far


def test_weighted_duration_by_market_uses_market_value_weights() -> None:
    short_bond = make_bond(isin="RU000S", duration_days=200)
    long_bond = make_bond(isin="RU000L", duration_days=1000)
    universe = {short_bond.isin: short_bond, long_bond.isin: long_bond}
    holdings = [
        HoldingView(
            figi="f1",
            isin=short_bond.isin,
            name=short_bond.name,
            lots=1,
            quantity=1,
            lot_size=1,
            current_price_pct=100.0,
            current_nkd_rub=0.0,
            ytm=12.0,
            maturity_date=short_bond.maturity_date,
            offer_date=None,
            market_value_rub=10_000.0,
        ),
        HoldingView(
            figi="f2",
            isin=long_bond.isin,
            name=long_bond.name,
            lots=1,
            quantity=1,
            lot_size=1,
            current_price_pct=100.0,
            current_nkd_rub=0.0,
            ytm=12.0,
            maturity_date=long_bond.maturity_date,
            offer_date=None,
            market_value_rub=30_000.0,
        ),
    ]
    weighted = weighted_duration_by_market(holdings, universe)
    assert weighted is not None
    short_years = short_bond.duration_years or 0.0
    long_years = long_bond.duration_years or 0.0
    expected = (10_000 * short_years + 30_000 * long_years) / 40_000
    assert weighted == pytest.approx(expected)
