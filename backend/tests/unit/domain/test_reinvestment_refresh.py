"""Тесты пересчёта реинвест-слотов перед сделкой."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from bond_monitor.domain.portfolio.reinvestment import refresh_due_reinvest_slot_suggestions
from factories import make_bond


def test_refresh_due_reinvest_slot_updates_suggestion() -> None:
    """Перед сделкой пересчитываем suggested_isin по актуальному скорингу."""
    today = date(2026, 7, 5)
    new_repl = make_bond(isin="RU000NEW1", name="New pick", maturity=date(2027, 9, 1))
    slot = ReinvestmentSlot(
        trigger_date=date(2026, 7, 1),
        trigger_reason=ReinvestmentTriggerReason.MATURITY,
        expected_cash_rub=50_000.0,
        suggested_isin="RU000STALE",
        suggested_name="Stale pick",
        source_position_isin="RU000SRC1",
        gap_days=2,
    )
    portfolio = Portfolio(
        name="T",
        initial_amount_rub=100_000.0,
        horizon_date=date(2028, 1, 1),
        risk_profile=RiskProfile.NORMAL,
        api_trade_only=False,
    )
    refresh_due_reinvest_slot_suggestions(
        [slot],
        portfolio=portfolio,
        universe=[new_repl],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert slot.suggested_isin == new_repl.isin


def test_refresh_skips_manual_override() -> None:
    today = date(2026, 7, 5)
    manual = make_bond(isin="RU000MAN1", name="Manual", maturity=date(2027, 6, 1))
    better = make_bond(isin="RU000BET1", name="Better", maturity=date(2027, 9, 1))
    better.score = 99.0
    slot = ReinvestmentSlot(
        trigger_date=date(2026, 7, 1),
        trigger_reason=ReinvestmentTriggerReason.MATURITY,
        expected_cash_rub=50_000.0,
        suggested_isin=better.isin,
        confirmed_isin=manual.isin,
        source_position_isin="RU000SRC1",
        gap_days=2,
    )
    portfolio = Portfolio(
        name="T",
        initial_amount_rub=100_000.0,
        horizon_date=date(2028, 1, 1),
        risk_profile=RiskProfile.NORMAL,
        api_trade_only=False,
    )
    refresh_due_reinvest_slot_suggestions(
        [slot],
        portfolio=portfolio,
        universe=[manual, better],
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert slot.suggested_isin == better.isin
    assert slot.confirmed_isin == manual.isin
