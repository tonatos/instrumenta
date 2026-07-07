"""Расчёт вложенного капитала портфеля."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.portfolio.position_status import open_positions
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.shared.position_math import position_cost_basis


def invested_capital_rub(
    portfolio: Portfolio,
    *,
    account_money_rub: float | None = None,
) -> float:
    """Вложенный капитал: позиции на счёте + свободный кэш (TRADING) или стартовый бюджет."""
    if account_money_rub is not None:
        deployed = sum(
            position_cost_basis(position) for position in open_positions(portfolio.positions)
        )
        return round(deployed + account_money_rub, 2)

    if portfolio.is_trading:
        deployed = sum(
            position_cost_basis(position) for position in open_positions(portfolio.positions)
        )
        return round(deployed + portfolio.cash_balance_rub, 2)

    return round(portfolio.initial_amount_rub, 2)


def invested_capital_from_snapshot(portfolio: Portfolio, money_rub: Rub) -> float:
    """Вложенный капитал по снимку брокерского счёта."""
    return invested_capital_rub(portfolio, account_money_rub=float(money_rub))
