"""Тесты прогнозной прибыли и доходности при пополнении портфеля."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from bond_monitor.domain.portfolio.models import PortfolioMode
from bond_monitor.domain.portfolio.planner import build_plan

_spec = importlib.util.spec_from_file_location(
    "test_planner",
    Path(__file__).with_name("test_planner.py"),
)
_test_planner = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_test_planner)
_aa19dfd_portfolio = _test_planner._aa19dfd_portfolio
_aa19dfd_universe = _test_planner._aa19dfd_universe

TODAY = date(2026, 7, 7)
KEY_RATE = 16.0
TAX_RATE = 0.13


def _trading_portfolio_with_capital(
    *,
    acknowledged_top_ups_rub: float,
    scale: float = 1.0,
) -> object:
    """Портфель ~20k старт + масштабированные позиции под top-up."""
    portfolio = _aa19dfd_portfolio()
    portfolio.mode = PortfolioMode.TRADING
    portfolio.acknowledged_top_ups_rub = acknowledged_top_ups_rub
    for pos in portfolio.positions:
        pos.actual_lots = pos.lots
        if scale != 1.0:
            pos.lots = max(1, int(pos.lots * scale))
            pos.actual_lots = pos.lots
            pos.purchase_amount_rub = round(pos.purchase_dirty_price_rub * pos.lots * pos.lot_size, 2)
    return portfolio


def _deployed_capital(portfolio: object) -> float:
    total = 0.0
    for pos in portfolio.positions:
        if pos.actual_lots is not None and pos.actual_lots > 0:
            total += pos.purchase_dirty_price_rub * pos.actual_lots * pos.lot_size
        else:
            total += pos.purchase_amount_rub
    return total


def test_profit_baseline_includes_acknowledged_top_up() -> None:
    """При acknowledged top-up прибыль не считается от одного только initial."""
    portfolio = _trading_portfolio_with_capital(acknowledged_top_ups_rub=180_000.0, scale=11.0)
    money_rub = 2_982.08
    on_account = _deployed_capital(portfolio) + money_rub
    plan = build_plan(
        portfolio,
        _aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=money_rub,
        assume_best_put_outcome=False,
    )

    assert plan.invested_capital_rub == pytest.approx(on_account, rel=0.02)
    assert plan.total_net_profit_with_held_rub < on_account * 0.5
    assert plan.total_net_profit_with_held_rub > -on_account


def test_profit_baseline_from_positions_when_acknowledged_zero() -> None:
    """Если acknowledged отстаёт, база берётся из фактических позиций на счёте."""
    portfolio = _trading_portfolio_with_capital(acknowledged_top_ups_rub=0.0, scale=11.0)
    money_rub = 2_982.08
    deployed = _deployed_capital(portfolio)

    plan = build_plan(
        portfolio,
        _aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=money_rub,
        assume_best_put_outcome=False,
    )

    assert deployed > portfolio.initial_amount_rub * 5
    assert plan.invested_capital_rub >= deployed + money_rub - 1_000
    inflated_profit = plan.final_portfolio_value_rub - portfolio.initial_amount_rub
    assert plan.total_net_profit_with_held_rub < inflated_profit * 0.5


def test_profit_ignores_inflated_acknowledged_top_ups() -> None:
    """Завышенный acknowledged_top_ups не должен раздувать базу вложений."""
    portfolio = _trading_portfolio_with_capital(acknowledged_top_ups_rub=227_738.0, scale=11.0)
    money_rub = 3_357.39
    on_account = _deployed_capital(portfolio) + money_rub
    plan = build_plan(
        portfolio,
        _aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=money_rub,
        assume_best_put_outcome=False,
    )

    assert on_account < portfolio.initial_amount_rub + portfolio.acknowledged_top_ups_rub
    assert plan.invested_capital_rub == pytest.approx(on_account, rel=0.02)
    assert plan.total_net_profit_with_held_rub == pytest.approx(
        plan.final_portfolio_value_rub - on_account,
        abs=1.0,
    )


def test_expected_xirr_not_inflated_after_top_up() -> None:
    """Годовая доходность не должна быть астрономической после top-up."""
    portfolio = _trading_portfolio_with_capital(acknowledged_top_ups_rub=180_000.0, scale=11.0)
    plan = build_plan(
        portfolio,
        _aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
        account_snapshot_money_rub=2_982.08,
        assume_best_put_outcome=False,
    )

    assert plan.effective_annual_return_pct is not None
    assert plan.effective_annual_return_pct < 50.0
    assert plan.effective_annual_return_pct > -20.0


def test_simulation_unchanged_without_top_up() -> None:
    """Регрессия: симуляция без top-up сохраняет разумные метрики."""
    portfolio = _aa19dfd_portfolio()
    plan = build_plan(
        portfolio,
        _aa19dfd_universe(),
        today=TODAY,
        key_rate=KEY_RATE,
        tax_rate=TAX_RATE,
    )

    assert plan.invested_capital_rub == pytest.approx(portfolio.initial_amount_rub)
    assert plan.effective_annual_return_pct is not None
    assert plan.effective_annual_return_pct < 100.0
    assert plan.total_net_profit_with_held_rub < portfolio.initial_amount_rub
