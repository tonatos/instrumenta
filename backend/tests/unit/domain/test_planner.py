"""Unit tests for portfolio planner."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from bond_monitor.domain.trading.models import (
    FrozenForecast,
)
from bond_monitor.domain.portfolio.cashflow import (
    cashflow_rows_with_balance,
    journal_sort_key,
    merge_reinvestment_slots,
)
from bond_monitor.domain.portfolio.planner import (
    _net_redemption_amount,
    auto_compose,
    build_plan,
    prune_stale_slot_overrides,
    select_replacement,
    validate_replacement_bond,
)
from factories import aa19dfd_portfolio, aa19dfd_universe, make_bond, make_live_bond

_bond = make_bond


def test_validate_replacement_bond_rejects_maturity_before_purchase() -> None:
    bond = _bond(isin="RU0001", name="Test", maturity=date(2026, 6, 1))
    reason = validate_replacement_bond(
        bond,
        slot_purchase_date=date(2027, 1, 1),
        horizon=date(2027, 6, 1),
    )
    assert reason is not None


def test_validate_replacement_bond_accepts_valid() -> None:
    bond = _bond(isin="RU0002", name="Valid", maturity=date(2027, 3, 1))
    reason = validate_replacement_bond(
        bond,
        slot_purchase_date=date(2026, 6, 1),
        horizon=date(2027, 6, 1),
    )
    assert reason is None


def test_auto_compose_diversifies() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 1, 1)
    maturities = [
        date(2026, 3, 1),
        date(2026, 5, 1),
        date(2026, 7, 1),
        date(2026, 9, 1),
        date(2026, 11, 1),
        date(2027, 1, 1),
        date(2027, 3, 1),
    ]
    universe = [
        _bond(isin=f"RU000{i}", name=f"Bond {i}", maturity=maturities[i - 1]) for i in range(1, 8)
    ]
    positions, cash, _notes = auto_compose(
        initial_amount=400_000,
        universe=universe,
        profile=RiskProfile.NORMAL,
        horizon_date=horizon,
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
    )
    assert len(positions) >= 1
    assert cash >= 0


def test_auto_compose_excludes_distressed_bonds() -> None:
    """Distressed (<85% clean) bonds must not appear in initial auto-compose."""
    today = date(2026, 1, 1)
    horizon = date(2027, 1, 1)
    distressed = _bond(
        isin="RU000DST",
        name="EuroTrans distressed",
        maturity=date(2026, 9, 1),
        price=75.0,
        ytm=35.0,
        score=95.0,
    )
    quality = _bond(
        isin="RU000QAL",
        name="Quality bond",
        maturity=date(2026, 9, 1),
        price=99.0,
        ytm=16.0,
        score=70.0,
    )
    positions, _cash, _notes = auto_compose(
        initial_amount=200_000,
        universe=[distressed, quality],
        profile=RiskProfile.AGGRESSIVE,
        horizon_date=horizon,
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        api_trade_only=False,
    )
    assert positions
    assert all(p.isin != distressed.isin for p in positions)


def test_auto_compose_api_trade_only_excludes_non_tradable() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 1, 1)
    maturities = [date(2026, 3, 1), date(2026, 5, 1), date(2026, 7, 1)]
    universe = [
        _bond(
            isin="RU000API",
            name="API ok",
            maturity=maturities[0],
            api_trade_available=True,
        ),
        _bond(
            isin="RU000NOAPI",
            name="No API",
            maturity=maturities[1],
            api_trade_available=False,
        ),
        _bond(
            isin="RU000UNK",
            name="Unknown",
            maturity=maturities[2],
            api_trade_available=None,
        ),
    ]
    positions, _cash, notes = auto_compose(
        initial_amount=200_000,
        universe=universe,
        profile=RiskProfile.NORMAL,
        horizon_date=horizon,
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        api_trade_only=True,
    )
    assert positions
    assert all(p.isin == "RU000API" for p in positions)
    assert not any("не нашлось" in n for n in notes)


def test_build_plan_produces_cashflow() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 1, 1)
    bond = _bond(isin="RU0001", name="ОФЗ", maturity=date(2026, 12, 1))
    portfolio = Portfolio(
        id="test",
        name="Test",
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
    plan = build_plan(
        portfolio,
        [bond],
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        assume_best_put_outcome=True,
    )
    assert plan.final_portfolio_value_rub > 0
    assert len(plan.events) > 0
    assert len(plan.value_timeline) >= 2
    assert plan.value_timeline[0].date == today
    assert plan.value_timeline[-1].date == horizon
    assert plan.value_timeline[-1].total_value_rub == pytest.approx(
        plan.final_portfolio_value_rub, rel=0.01
    )


def test_select_replacement_failure_explains_narrow_window() -> None:
    bond, reason = select_replacement(
        [_bond(isin="RU0099", name="Far", maturity=date(2028, 1, 1))],
        target_date=date(2027, 7, 6),
        profile=RiskProfile.AGGRESSIVE,
        amount=100_000,
        horizon_date=date(2027, 7, 15),
        key_rate=14.5,
        tax_rate=0.13,
    )

    assert bond is None
    assert "окно реинвестиции слишком узкое" in reason
    assert "16 июля 2027" in reason


def test_select_replacement_failure_explains_lot_too_expensive() -> None:
    bond, reason = select_replacement(
        [_bond(isin="RU0100", name="Pricey", maturity=date(2027, 8, 1), price=99.0)],
        target_date=date(2027, 6, 24),
        profile=RiskProfile.AGGRESSIVE,
        amount=500,
        horizon_date=date(2027, 9, 1),
        key_rate=14.5,
        tax_rate=0.13,
    )

    assert bond is None
    assert "мин. лот" in reason
    assert "500" in reason
    assert "aggressive" in reason


def test_build_plan_note_explains_missing_replacement() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 7, 15)
    maturing = _bond(isin="RU0001", name="НовТех1Р7", maturity=date(2027, 6, 22))
    portfolio = Portfolio(
        id="test",
        name="Test",
        initial_amount_rub=100_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.AGGRESSIVE,
        positions=[
            PortfolioPosition(
                isin=maturing.isin,
                secid=maturing.secid,
                name=maturing.name,
                lots=10,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=99_000,
                maturity_date=maturing.maturity_date,
                offer_date=None,
                coupon_rate=12.0,
                coupon_period_days=182,
                next_coupon_date=date(2026, 7, 1),
            )
        ],
    )

    plan = build_plan(
        portfolio,
        [maturing],
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        assume_best_put_outcome=True,
    )

    missing_notes = [
        note
        for note in plan.notes
        if "не нашлось подходящей замены" in note and "НовТех1Р7" in note
    ]
    assert len(missing_notes) == 1
    assert "не нашлось подходящей замены" in missing_notes[0]
    assert "кэш-балансе" in missing_notes[0]


def test_build_plan_slot_includes_suggested_name() -> None:
    """После волнового реинвеста слот содержит suggested_isin/name из compose."""
    today = date(2026, 1, 1)
    horizon = date(2027, 6, 1)
    maturity = date(2026, 6, 1)
    purchase_date = maturity + timedelta(days=2)
    held = _bond(isin="RU000HELD1", name="Held", maturity=maturity, ytm=12.0)
    replacements = [
        _bond(isin=f"RU000R{i}", name=f"Repl {i}", maturity=date(2027, 3, 1 + i), ytm=10.0 + i)
        for i in range(6)
    ]
    portfolio = Portfolio(
        id="test",
        name="Test",
        initial_amount_rub=30_000.0,
        horizon_date=horizon,
        risk_profile=RiskProfile.NORMAL,
        api_trade_only=False,
        positions=[
            PortfolioPosition(
                isin=held.isin,
                secid=held.secid,
                name=held.name,
                lots=80,
                lot_size=1,
                face_value=1000,
                purchase_date=today,
                purchase_clean_price_pct=99.0,
                purchase_dirty_price_rub=990.0,
                purchase_aci_rub=0.0,
                purchase_amount_rub=79_200.0,
                maturity_date=held.maturity_date,
                offer_date=None,
                coupon_rate=12.0,
                coupon_period_days=182,
                next_coupon_date=date(2026, 3, 1),
                source=PositionSourceType.INITIAL,
            )
        ],
    )

    plan = build_plan(
        portfolio,
        [held, *replacements],
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        assume_best_put_outcome=True,
    )

    slots_with_suggestion = [
        s
        for s in plan.resolved_slots
        if s.suggested_isin and s.purchase_date == purchase_date
    ]
    assert slots_with_suggestion
    slot = slots_with_suggestion[0]
    assert slot.suggested_isin is not None
    assert slot.suggested_name is not None


def test_build_plan_resolved_slots_sorted_by_trigger_date() -> None:
    """Слоты реинвестиции выдаются по возрастанию trigger_date, не по порядку позиций."""
    today = date(2026, 1, 1)
    horizon = date(2027, 12, 1)
    maturing_later = _bond(isin="RU000LATE", name="Late bond", maturity=date(2027, 6, 1))
    maturing_earlier = _bond(isin="RU000EARLY", name="Early bond", maturity=date(2026, 6, 1))
    replacement = _bond(isin="RU000REPL", name="Replacement", maturity=date(2027, 9, 1))

    def _position(bond: BondRecord) -> PortfolioPosition:
        return PortfolioPosition(
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
            purchase_amount_rub=9_900,
            maturity_date=bond.maturity_date,
            offer_date=None,
            coupon_rate=12.0,
            coupon_period_days=182,
            next_coupon_date=date(2026, 7, 1),
        )

    portfolio = Portfolio(
        id="test",
        name="Test",
        initial_amount_rub=100_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.NORMAL,
        positions=[
            _position(maturing_later),
            _position(maturing_earlier),
        ],
    )

    plan = build_plan(
        portfolio,
        [maturing_later, maturing_earlier, replacement],
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        assume_best_put_outcome=True,
    )

    source_slots = [
        s
        for s in plan.resolved_slots
        if s.source_position_isin in (maturing_earlier.isin, maturing_later.isin)
    ]
    assert len(source_slots) >= 2
    trigger_dates = [s.trigger_date for s in source_slots]
    assert trigger_dates == sorted(trigger_dates)
    assert source_slots[0].trigger_date == maturing_earlier.maturity_date


def _position(
    *,
    isin: str,
    name: str,
    lots: int,
    purchase_amount_rub: float,
    bond: BondRecord,
    coupon_date: date,
) -> PortfolioPosition:
    return PortfolioPosition(
        isin=isin,
        secid=bond.secid,
        name=name,
        lots=lots,
        lot_size=1,
        face_value=1000,
        purchase_date=date(2026, 1, 1),
        purchase_clean_price_pct=99.0,
        purchase_dirty_price_rub=990.0,
        purchase_aci_rub=0.0,
        purchase_amount_rub=purchase_amount_rub,
        maturity_date=bond.maturity_date,
        offer_date=None,
        coupon_rate=12.0,
        coupon_period_days=182,
        next_coupon_date=coupon_date,
        source=PositionSourceType.INITIAL,
    )


def test_build_plan_merges_coupons_for_same_isin_positions() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 1, 1)
    coupon_date = date(2026, 7, 1)
    bond = _bond(isin="RU0001", name="МигКр 04", maturity=date(2026, 12, 1))
    portfolio = Portfolio(
        id="test",
        name="Test",
        initial_amount_rub=200_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.NORMAL,
        positions=[
            _position(
                isin=bond.isin,
                name=bond.name,
                lots=10,
                purchase_amount_rub=99_000,
                bond=bond,
                coupon_date=coupon_date,
            ),
            _position(
                isin=bond.isin,
                name=bond.name,
                lots=5,
                purchase_amount_rub=49_500,
                bond=bond,
                coupon_date=coupon_date,
            ),
        ],
    )
    plan = build_plan(
        portfolio,
        [bond],
        today=today,
        key_rate=14.5,
        tax_rate=0.13,
        assume_best_put_outcome=True,
    )
    coupons_on_date = [
        e
        for e in plan.events
        if e.kind == "coupon" and e.date == coupon_date and e.related_isin == bond.isin
    ]
    assert len(coupons_on_date) == 1
    net_factor = 1.0 - 0.13
    expected_per_bond = 1000 * (12.0 / 100.0) * (182 / 365.0) * net_factor
    assert coupons_on_date[0].amount_rub == pytest.approx(expected_per_bond * 15, rel=0.01)


def test_merge_reinvestment_slots_combines_same_source_maturity() -> None:
    d = date(2026, 10, 8)
    isin = "RU000A109TG2"
    slots = [
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=67_622.0,
            suggested_isin="RU000REPL",
            suggested_name="Replacement",
            source_position_isin=isin,
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=68_616.0,
            suggested_isin="RU000REPL",
            suggested_name="Replacement",
            source_position_isin=isin,
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=73_588.0,
            suggested_isin="RU000REPL",
            suggested_name="Replacement",
            source_position_isin=isin,
        ),
    ]
    merged = merge_reinvestment_slots(slots)
    maturities = [s for s in merged if s.trigger_reason == ReinvestmentTriggerReason.MATURITY]
    assert len(maturities) == 1
    assert maturities[0].expected_cash_rub == pytest.approx(209_826.0)
    assert maturities[0].source_position_isin == isin


def test_merge_reinvestment_slots_combines_coupon_cash_on_same_date() -> None:
    d = date(2026, 6, 15)
    slots = [
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.COUPON_CASH,
            expected_cash_rub=5_000.0,
            suggested_isin="RU0001",
            suggested_name="Bond A",
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.COUPON_CASH,
            expected_cash_rub=3_200.0,
            suggested_isin="RU0002",
            suggested_name="Bond B",
        ),
    ]
    merged = merge_reinvestment_slots(slots)
    coupon_slots = [s for s in merged if s.trigger_reason == ReinvestmentTriggerReason.COUPON_CASH]
    assert len(coupon_slots) == 1
    assert coupon_slots[0].expected_cash_rub == pytest.approx(8_200.0)


def test_merge_reinvestment_slots_keeps_different_sources_and_reasons() -> None:
    d = date(2026, 10, 8)
    slots = [
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=10_000.0,
            source_position_isin="RU0001",
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=20_000.0,
            source_position_isin="RU0002",
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.PUT_OFFER,
            expected_cash_rub=15_000.0,
            source_position_isin="RU0001",
        ),
    ]
    merged = merge_reinvestment_slots(slots)
    assert len(merged) == 3


def test_merge_reinvestment_slots_coalesces_maturity_and_coupon_cash_same_purchase() -> None:
    """Сценарий портфеля aa19dfd359c5489988adac94df8bfe8b: погашение + купонный кэш в один день."""
    d = date(2026, 8, 6)
    target = "RU000A107RZ0"
    slots = [
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=5_985.31,
            suggested_isin=target,
            suggested_name="СамолетP13",
            gap_days=2,
            source_position_isin="RU000A109908",
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.COUPON_CASH,
            expected_cash_rub=27_273.0,
            suggested_isin=target,
            suggested_name="СамолетP13",
            gap_days=2,
        ),
    ]
    merged = merge_reinvestment_slots(slots)
    assert len(merged) == 1
    assert merged[0].trigger_date == d
    assert merged[0].trigger_reason == ReinvestmentTriggerReason.MATURITY
    assert merged[0].expected_cash_rub == pytest.approx(33_258.31, rel=0.01)
    assert merged[0].source_position_isin == "RU000A109908"
    assert merged[0].purchase_date == date(2026, 8, 8)


def test_merge_reinvestment_slots_keeps_same_date_different_targets() -> None:
    d = date(2027, 6, 18)
    slots = [
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=11_952.7,
            suggested_isin="RU000A108RK0",
            suggested_name="iПМЕДДМ2Р2",
            gap_days=2,
            source_position_isin="RU000A108RK0",
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.COUPON_CASH,
            expected_cash_rub=2_882.95,
            suggested_isin="RU000OTHER",
            suggested_name="Other",
            gap_days=2,
        ),
    ]
    merged = merge_reinvestment_slots(slots)
    assert len(merged) == 2


def test_merge_reinvestment_slots_preserves_confirmed_isin() -> None:
    d = date(2026, 10, 8)
    slots = [
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=10_000.0,
            suggested_isin="RU000AUTO",
            source_position_isin="RU0001",
        ),
        ReinvestmentSlot(
            trigger_date=d,
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=5_000.0,
            suggested_isin="RU000OTHER",
            confirmed_isin="RU000USER",
            source_position_isin="RU0001",
        ),
    ]
    merged = merge_reinvestment_slots(slots)
    assert len(merged) == 1
    assert merged[0].confirmed_isin == "RU000USER"
    assert merged[0].expected_cash_rub == pytest.approx(15_000.0)


def test_build_plan_merges_reinvestment_slots_for_same_isin_positions() -> None:
    today = date(2026, 1, 1)
    horizon = date(2027, 6, 1)
    maturity = date(2026, 12, 1)
    replacement = _bond(isin="RU000REPL", name="Replacement", maturity=date(2027, 3, 1))
    bond = _bond(isin="RU0001", name="МигКр 04", maturity=maturity)
    tax_rate = 0.13

    def _maturity_position(*, lots: int, purchase_amount_rub: float) -> PortfolioPosition:
        return PortfolioPosition(
            isin=bond.isin,
            secid=bond.secid,
            name=bond.name,
            lots=lots,
            lot_size=1,
            face_value=1000,
            purchase_date=today,
            purchase_clean_price_pct=99.0,
            purchase_dirty_price_rub=990.0,
            purchase_aci_rub=0.0,
            purchase_amount_rub=purchase_amount_rub,
            maturity_date=bond.maturity_date,
            offer_date=None,
            coupon_rate=12.0,
            coupon_period_days=182,
            next_coupon_date=date(2026, 7, 1),
            source=PositionSourceType.INITIAL,
        )

    pos_a = _maturity_position(lots=10, purchase_amount_rub=99_000)
    pos_b = _maturity_position(lots=5, purchase_amount_rub=49_500)
    portfolio = Portfolio(
        id="test",
        name="Test",
        initial_amount_rub=200_000,
        horizon_date=horizon,
        risk_profile=RiskProfile.NORMAL,
        positions=[pos_a, pos_b],
    )
    plan = build_plan(
        portfolio,
        [bond, replacement],
        today=today,
        key_rate=14.5,
        tax_rate=tax_rate,
        assume_best_put_outcome=True,
    )
    maturity_slots = [
        s
        for s in plan.resolved_slots
        if s.trigger_date == maturity and s.source_position_isin == bond.isin
    ]
    assert len(maturity_slots) == 1
    redemption_total = _net_redemption_amount(pos_a, tax_rate) + _net_redemption_amount(
        pos_b, tax_rate
    )
    assert maturity_slots[0].expected_cash_rub >= redemption_total - 0.01


def test_build_plan_emits_initial_purchases_in_simulation() -> None:
    today = date(2026, 7, 7)
    portfolio = aa19dfd_portfolio()
    plan = build_plan(
        portfolio,
        aa19dfd_universe(),
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
    )

    initial_purchases = [
        e
        for e in plan.events
        if e.kind == "purchase" and e.date == today and e.is_projected is False
    ]
    assert len(initial_purchases) == 3

    running = portfolio.initial_amount_rub
    for event in sorted(plan.events, key=journal_sort_key):
        running += event.amount_rub
        assert running >= -0.01, event.description
    assert running == pytest.approx(plan.final_cash_balance_rub, rel=0.01)


def test_horizon_extension_rebuilds_reinvestment_chain_for_trading_portfolio() -> None:
    """Extending horizon must add forecast reinvestment slots; facts stay intact."""
    today = date(2026, 7, 7)
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.frozen_forecast = FrozenForecast(
        expected_xirr_pct=18.0,
        expected_total_net_profit_rub=5_000.0,
        expected_final_value_rub=25_000.0,
        frozen_initial_amount_rub=20_000.0,
        horizon_date=date(2027, 1, 1),
    )
    positions_snapshot = [(p.isin, p.lots, p.purchase_amount_rub) for p in portfolio.positions]
    frozen_snapshot = portfolio.frozen_forecast

    plan_short = build_plan(
        portfolio,
        aa19dfd_universe(),
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=portfolio.cash_balance_rub,
        assume_best_put_outcome=False,
    )
    portfolio.horizon_date = date(2028, 1, 1)
    plan_long = build_plan(
        portfolio,
        aa19dfd_universe(),
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=portfolio.cash_balance_rub,
        assume_best_put_outcome=False,
    )

    assert len(plan_long.resolved_slots) > len(plan_short.resolved_slots)
    assert [(p.isin, p.lots, p.purchase_amount_rub) for p in portfolio.positions] == positions_snapshot
    assert portfolio.frozen_forecast == frozen_snapshot


def test_prune_stale_slot_overrides_drops_phantom_sources_beyond_horizon() -> None:
    today = date(2026, 7, 7)
    portfolio = aa19dfd_portfolio()
    portfolio.slots = [
        ReinvestmentSlot(
            trigger_date=date(2026, 12, 31),
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=10_000.0,
            source_position_isin="RU000A107KR2",
            confirmed_isin="RU000A107KR2",
        ),
        ReinvestmentSlot(
            trigger_date=date(2026, 7, 28),
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=5_000.0,
            source_position_isin="RU000A100PB0",
            confirmed_isin="RU000A107BH2",
        ),
    ]
    plan = build_plan(
        portfolio,
        aa19dfd_universe(),
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
    )
    active_sources = {s.source_position_isin for s in plan.resolved_slots if s.source_position_isin}
    assert "RU000A107KR2" not in active_sources
    assert all(slot.source_position_isin in active_sources for slot in portfolio.slots)
    assert any(slot.source_position_isin == "RU000A100PB0" for slot in portfolio.slots)


def test_prune_stale_slot_overrides_helper() -> None:
    portfolio = Portfolio(
        id="p1",
        name="Test",
        initial_amount_rub=100_000,
        horizon_date=date(2027, 6, 1),
        risk_profile=RiskProfile.NORMAL,
        slots=[
            ReinvestmentSlot(
                trigger_date=date(2026, 6, 1),
                trigger_reason=ReinvestmentTriggerReason.MATURITY,
                expected_cash_rub=10_000,
                source_position_isin="KEEP",
                confirmed_isin="RU0001",
            ),
            ReinvestmentSlot(
                trigger_date=date(2026, 12, 1),
                trigger_reason=ReinvestmentTriggerReason.MATURITY,
                expected_cash_rub=10_000,
                source_position_isin="DROP",
                confirmed_isin="RU0002",
            ),
        ],
    )
    resolved = [
        ReinvestmentSlot(
            trigger_date=date(2026, 6, 1),
            trigger_reason=ReinvestmentTriggerReason.MATURITY,
            expected_cash_rub=10_000,
            source_position_isin="KEEP",
        ),
    ]
    changed = prune_stale_slot_overrides(portfolio, resolved)
    assert changed
    assert [s.source_position_isin for s in portfolio.slots] == ["KEEP"]


def test_build_plan_includes_plan_positions() -> None:
    today = date(2026, 7, 1)
    portfolio = Portfolio(
        name="Positions test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2028, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    open_pos = PortfolioPosition(
        isin="RU000OPEN",
        secid="OPEN",
        name="Open bond",
        lots=5,
        lot_size=1,
        purchase_clean_price_pct=95.0,
        purchase_dirty_price_rub=960.0,
        purchase_aci_rub=10.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=4800.0,
        coupon_rate=10.0,
        face_value=1000.0,
        maturity_date=date(2027, 6, 1),
        offer_date=None,
        coupon_period_days=182,
        source=PositionSourceType.INITIAL,
        next_coupon_date=date(2026, 12, 1),
    )
    portfolio.positions = [open_pos]
    universe = [_bond(isin="RU000OPEN", name="Open bond", maturity=date(2027, 6, 1))]
    plan = build_plan(portfolio, universe, today=today, key_rate=16.0, tax_rate=0.13)
    assert "RU000OPEN" in {p.isin for p in plan.all_positions}


def test_plan_cashflow_running_balance_never_negative() -> None:
    """Cashflow-таблица не должна уходить в минус (в т.ч. после merge покупок)."""
    from bond_monitor.domain.portfolio.cashflow import cashflow_rows_with_balance

    today = date(2026, 7, 7)
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    plan = build_plan(
        portfolio,
        aa19dfd_universe(),
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=portfolio.cash_balance_rub,
        assume_best_put_outcome=False,
    )
    rows = cashflow_rows_with_balance(plan.events, plan.initial_cash_rub)
    assert plan.initial_cash_rub == pytest.approx(portfolio.cash_balance_rub)
    for row in rows:
        assert row["balance_after_rub"] >= -0.01

    sim_plan = build_plan(
        aa19dfd_portfolio(),
        aa19dfd_universe(),
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
    )
    sim_rows = cashflow_rows_with_balance(sim_plan.events, sim_plan.initial_cash_rub)
    for row in sim_rows:
        assert row["balance_after_rub"] >= -0.01


def test_build_plan_trading_put_offer_in_cashflow() -> None:
    """TRADING: пут-оферта по номиналу попадает в cashflow и слоты реинвеста."""
    today = date(2026, 7, 8)
    offer_date = date(2026, 8, 7)
    maturity = date(2027, 7, 30)
    replacement = _bond(isin="RU000REPL", name="Замена", maturity=date(2027, 9, 1))
    bond = _bond(
        isin="RU000A109874",
        name="СамолетP15",
        maturity=maturity,
        offer_date=offer_date,
        effective_date=offer_date,
        offer_price_pct=100.0,
        coupon_rate=12.0,
        coupon_period_days=91,
        next_coupon_date=date(2026, 10, 7),
    )
    position = PortfolioPosition(
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
        maturity_date=maturity,
        offer_date=offer_date,
        offer_price_pct=100.0,
        coupon_rate=12.0,
        coupon_period_days=91,
        next_coupon_date=date(2026, 10, 7),
        source=PositionSourceType.ADOPTED,
    )
    portfolio = Portfolio(
        id="put-offer-cf",
        name="Put offer cashflow",
        initial_amount_rub=100_000,
        horizon_date=date(2028, 1, 1),
        risk_profile=RiskProfile.NORMAL,
        mode=PortfolioMode.TRADING,
        positions=[position],
        cash_balance_rub=1_000.0,
    )

    plan = build_plan(
        portfolio,
        [bond, replacement],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        account_snapshot_money_rub=portfolio.cash_balance_rub,
        assume_best_put_outcome=False,
    )

    put_events = [
        e
        for e in plan.events
        if e.kind == "put_offer" and e.related_isin == bond.isin and e.date == offer_date
    ]
    assert len(put_events) == 1

    put_slots = [
        s
        for s in plan.resolved_slots
        if s.trigger_reason == ReinvestmentTriggerReason.PUT_OFFER
        and s.source_position_isin == bond.isin
    ]
    assert len(put_slots) == 1
    assert put_slots[0].trigger_date == offer_date
