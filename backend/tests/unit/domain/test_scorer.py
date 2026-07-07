"""Unit tests for bond scoring."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, CouponType, RiskLevel
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.screening.scorer import (
    _scoring_ytm_net,
    calc_distress_penalty,
    calc_liquidity_score,
    calc_risk_score,
    calc_ytm_score,
    score_bonds,
    score_bonds_for_profile,
)


def test_calc_ytm_score_higher_for_better_ytm() -> None:
    low = calc_ytm_score(10.0, risk_free_net=12.0, max_spread=8.0)
    high = calc_ytm_score(18.0, risk_free_net=12.0, max_spread=8.0)
    assert high > low


def test_score_bonds_fills_ytm_net() -> None:
    bonds = [
        BondRecord(
            secid="TEST",
            isin="RU000TEST",
            name="Test",
            ytm=16.0,
            risk_level=RiskLevel.LOW,
            volume_rub=1_000_000,
            maturity_date=date(2026, 12, 1),
        )
    ]
    scored = score_bonds(bonds, key_rate=14.5, tax_rate=0.13)
    assert scored[0].ytm_net is not None
    assert scored[0].score is not None


def _make_bond(
    *,
    secid: str,
    ytm: float,
    credit_rating: str | None = None,
    prev_volume_rub: float = 5_000_000,
    risk_level: RiskLevel = RiskLevel.HIGH,
    coupon_type: CouponType = CouponType.FIXED,
    floating_coupon_flag: bool = False,
) -> BondRecord:
    return BondRecord(
        secid=secid,
        isin=f"RU000{secid}",
        name=secid,
        ytm=ytm,
        credit_rating=credit_rating,
        risk_level=risk_level,
        prev_volume_rub=prev_volume_rub,
        maturity_date=date(2026, 12, 1),
        coupon_type=coupon_type,
        floating_coupon_flag=floating_coupon_flag,
    )


def test_unrated_ranks_below_equal_ytm_rated_bond() -> None:
    """Unrated junk must not outrank a BB-rated peer with the same YTM."""
    bonds = [
        _make_bond(secid="UNRATED", ytm=30.0, credit_rating=None),
        _make_bond(secid="RATED", ytm=30.0, credit_rating="ruBB"),
    ]
    scored = score_bonds_for_profile(
        bonds,
        RiskProfile.AGGRESSIVE,
        key_rate=14.5,
        tax_rate=0.13,
    )
    by_secid = {b.secid: b for b in scored}
    assert by_secid["RATED"].score is not None
    assert by_secid["UNRATED"].score is not None
    assert by_secid["RATED"].score > by_secid["UNRATED"].score
    assert scored[0].secid == "RATED"


def test_distress_ytm_loses_to_moderate_bond() -> None:
    """60% YTM distressed issue must rank below a healthy ~25% YTM BB bond."""
    bonds = [
        _make_bond(secid="DISTRESS", ytm=60.0, credit_rating="ruBB"),
        _make_bond(secid="HEALTHY", ytm=25.0, credit_rating="ruBB"),
    ]
    scored = score_bonds_for_profile(
        bonds,
        RiskProfile.AGGRESSIVE,
        key_rate=14.5,
        tax_rate=0.13,
    )
    by_secid = {b.secid: b for b in scored}
    assert by_secid["HEALTHY"].score is not None
    assert by_secid["DISTRESS"].score is not None
    assert by_secid["HEALTHY"].score > by_secid["DISTRESS"].score
    assert scored[0].secid == "HEALTHY"


def test_aggressive_prefers_vdo_over_low_yield_ig() -> None:
    """~35% VDO must beat ~20% AA- for aggressive portfolio ranking."""
    bonds = [
        _make_bond(
            secid="VDO",
            ytm=35.0,
            credit_rating="ruBBB-",
            risk_level=RiskLevel.MODERATE,
        ),
        _make_bond(
            secid="IG",
            ytm=20.65,
            credit_rating="ruAA-",
            risk_level=RiskLevel.LOW,
            prev_volume_rub=50_000_000,
        ),
    ]
    scored = score_bonds_for_profile(
        bonds,
        RiskProfile.AGGRESSIVE,
        key_rate=14.5,
        tax_rate=0.13,
    )
    by_secid = {b.secid: b for b in scored}
    assert by_secid["VDO"].score is not None
    assert by_secid["IG"].score is not None
    assert by_secid["VDO"].score > by_secid["IG"].score
    assert scored[0].secid == "VDO"


def test_floating_coupon_has_no_extra_risk_penalty() -> None:
    """Floating coupon must not reduce risk score vs fixed peer."""
    fixed = _make_bond(secid="FIXED", ytm=30.0, credit_rating="ruBBB-")
    floating = _make_bond(
        secid="FLOAT",
        ytm=30.0,
        credit_rating="ruBBB-",
        coupon_type=CouponType.FLOATING,
        floating_coupon_flag=True,
    )
    risk_free_net = 14.5 * (1 - 0.13)
    assert calc_risk_score(fixed) == calc_risk_score(floating)
    assert calc_distress_penalty(fixed, fixed.ytm * 0.87, risk_free_net) == calc_distress_penalty(
        floating, floating.ytm * 0.87, risk_free_net
    )


def test_extreme_ytm_keeps_nonzero_ytm_score() -> None:
    """~70% YTM must not collapse ytm_score to literal zero."""
    risk_free_net = 14.5 * (1 - 0.13)
    ytm_net = 69.39 * (1 - 0.13)
    score = calc_ytm_score(ytm_net, risk_free_net, max_spread=40.0)
    assert score > 0.0


def test_thin_volume_gets_low_liquidity_score() -> None:
    """212k RUB/day is illiquid — score must stay well below mid-scale."""
    score = calc_liquidity_score(212_077)
    assert score < 20.0


def test_liquidity_score_uses_absolute_anchors() -> None:
    """Liquidity must not depend on universe max volume."""
    floor_score = calc_liquidity_score(500_000)
    good_score = calc_liquidity_score(10_000_000)
    mid_score = calc_liquidity_score(2_000_000)

    assert floor_score == 0.0
    assert good_score == 100.0
    assert 40.0 < mid_score < 55.0
    assert calc_liquidity_score(2_000_000) == mid_score


def test_calc_distress_penalty_zero_below_threshold() -> None:
    risk_free_net = 14.5 * (1 - 0.13)
    bond = _make_bond(secid="X", ytm=20.0, credit_rating="ruBB")
    assert calc_distress_penalty(bond, risk_free_net + 10.0, risk_free_net) == 0.0


def test_calc_distress_penalty_ig_has_higher_threshold() -> None:
    risk_free_net = 14.5 * (1 - 0.13)
    ig = _make_bond(secid="IG", ytm=35.0, credit_rating="ruBBB-")
    junk = _make_bond(secid="JUNK", ytm=35.0, credit_rating="ruBB")
    spread = risk_free_net + 32.0
    assert calc_distress_penalty(ig, spread, risk_free_net) == 0.0
    assert calc_distress_penalty(junk, spread, risk_free_net) > 0.0


def test_scoring_ytm_net_caps_phantom_yield_to_call() -> None:
    """Callable bond: scoring uses coupon yield, not phantom yield-to-call."""
    bond = BondRecord(
        secid="CALL",
        isin="RU000CALL",
        name="CALL",
        ytm=68.66,
        ytm_net=68.66 * 0.87,
        coupon_rate=24.0,
        call_date=date(2026, 10, 6),
        maturity_date=date(2027, 9, 30),
        risk_level=RiskLevel.HIGH,
        credit_rating="ruB+",
    )
    risk_free_net = 14.5 * 0.87
    scoring = _scoring_ytm_net(bond, risk_free_net, after_tax_multiplier=0.87)
    assert scoring == 24.0 * 0.87
    assert scoring < bond.ytm_net


def test_callable_bond_ranks_below_equivalent_non_call() -> None:
    """Phantom yield-to-call must not outrank same credit at maturity yield."""
    plain = BondRecord(
        secid="PLAIN",
        isin="RU000PLAIN",
        name="PLAIN",
        ytm=28.0,
        coupon_rate=24.0,
        credit_rating="ruBBB-",
        risk_level=RiskLevel.MODERATE,
        prev_volume_rub=876_592,
        maturity_date=date(2027, 9, 30),
    )
    callable_bond = BondRecord(
        secid="CALL",
        isin="RU000CALL",
        name="CALL",
        ytm=68.66,
        coupon_rate=24.0,
        call_date=date(2026, 10, 6),
        credit_rating="ruBBB-",
        risk_level=RiskLevel.MODERATE,
        prev_volume_rub=876_592,
        maturity_date=date(2027, 9, 30),
    )
    scored = score_bonds_for_profile(
        [callable_bond, plain],
        RiskProfile.AGGRESSIVE,
        key_rate=14.5,
        tax_rate=0.13,
    )
    by_secid = {b.secid: b for b in scored}
    assert by_secid["PLAIN"].score is not None
    assert by_secid["CALL"].score is not None
    assert by_secid["PLAIN"].score > by_secid["CALL"].score


def test_callable_bond_has_stronger_risk_penalty_than_plain() -> None:
    bond = BondRecord(
        secid="CALL",
        isin="RU000CALL",
        name="CALL",
        call_date=date(2026, 10, 6),
        risk_level=RiskLevel.MODERATE,
        credit_rating="ruBBB-",
    )
    plain = BondRecord(
        secid="PLAIN",
        isin="RU000PLAIN",
        name="PLAIN",
        risk_level=RiskLevel.MODERATE,
        credit_rating="ruBBB-",
    )
    assert calc_risk_score(bond) < calc_risk_score(plain)
    assert calc_risk_score(plain) - calc_risk_score(bond) == 12.0
