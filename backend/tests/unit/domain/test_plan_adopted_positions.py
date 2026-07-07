"""Прогноз не должен вырезать ADOPTED-позиции как фантомы реинвестиции."""

from __future__ import annotations

from datetime import date

import pytest

from bond_monitor.domain.portfolio.models import PortfolioMode, PositionSourceType
from bond_monitor.domain.portfolio.planner import build_plan
from factories import aa19dfd_portfolio, aa19dfd_universe

TODAY = date(2026, 7, 7)
KEY_RATE = 16.0
TAX_RATE = 0.13


def _trading_portfolio_with_adopted(*, money_rub: float) -> object:
    portfolio = aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    for pos in portfolio.positions:
        pos.actual_lots = pos.lots
    portfolio.positions[-1].source = PositionSourceType.ADOPTED
    portfolio.positions[-2].source = PositionSourceType.ADOPTED
    return portfolio


def test_adopted_positions_keep_coupons_in_trading_plan() -> None:
    """ADOPTED уже на счёте: остаются в плане и не вырезаются cap-ом по кэшу."""
    portfolio = _trading_portfolio_with_adopted(money_rub=2_242.0)
    adopted_isins = {
        pos.isin for pos in portfolio.positions if pos.source == PositionSourceType.ADOPTED
    }

    plan = build_plan(
        portfolio,
        aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=2_242.0,
        assume_best_put_outcome=False,
    )

    plan_isins = {pos.isin for pos in plan.all_positions}
    assert adopted_isins <= plan_isins

    cashflow_isins = {
        event.related_isin
        for event in plan.events
        if event.kind in ("coupon", "maturity", "put_offer")
    }
    assert adopted_isins <= cashflow_isins


def test_adopted_positions_do_not_fake_massive_loss() -> None:
    """Регрессия: ADOPTED не должны давать −30% из-за prune по cap кэша."""
    portfolio_all_initial = aa19dfd_portfolio()
    for pos in portfolio_all_initial.positions:
        pos.actual_lots = pos.lots
    portfolio_all_initial.mode = PortfolioMode.TRADING

    portfolio_with_adopted = _trading_portfolio_with_adopted(money_rub=2_242.0)

    plan_initial = build_plan(
        portfolio_all_initial,
        aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=2_242.0,
        assume_best_put_outcome=False,
    )
    plan_adopted = build_plan(
        portfolio_with_adopted,
        aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=2_242.0,
        assume_best_put_outcome=False,
    )

    assert plan_adopted.final_portfolio_value_rub == pytest.approx(
        plan_initial.final_portfolio_value_rub,
        rel=0.02,
    )
    assert plan_adopted.total_net_profit_with_held_rub == pytest.approx(
        plan_initial.total_net_profit_with_held_rub,
        rel=0.02,
    )
    assert plan_adopted.effective_annual_return_pct is not None
    assert plan_adopted.effective_annual_return_pct > -20.0
