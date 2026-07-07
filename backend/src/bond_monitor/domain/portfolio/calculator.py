"""Расчёт доходности удержания облигации до оферты/погашения (без налога)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import PortfolioPosition
from bond_monitor.domain.portfolio.planner import (
    _coupon_dates_in_range,
    _coupon_payment_per_event,
    position_from_bond,
)


@dataclass(frozen=True)
class BondHoldResult:
    secid: str
    name: str
    lots: int
    invested_rub: float
    coupon_income_rub: float
    redemption_rub: float
    profit_rub: float
    hold_days: int
    yield_pct: float | None


@dataclass(frozen=True)
class PortfolioHoldResult:
    positions: list[BondHoldResult]
    total_invested_rub: float
    total_profit_rub: float
    portfolio_yield_pct: float | None


def _hold_end_date(bond: BondRecord, today: date) -> date | None:
    end = bond.effective_date or bond.maturity_date
    if end is None or end <= today:
        return None
    return end


def _redemption_amount_gross(position: PortfolioPosition, end_date: date) -> float:
    if position.offer_date is not None and end_date == position.offer_date:
        price_pct = position.offer_price_pct if position.offer_price_pct is not None else 100.0
        per_bond = position.face_value * (price_pct / 100.0)
    else:
        per_bond = position.face_value
    return per_bond * position.bonds_count


def _coupon_income_gross(position: PortfolioPosition, end_date: date) -> float:
    payment = _coupon_payment_per_event(position)
    if payment <= 0:
        return 0.0
    dates = _coupon_dates_in_range(position, end_date)
    return payment * len(dates)


def calculate_bond_hold(
    bond: BondRecord,
    *,
    lots: int,
    today: date,
) -> BondHoldResult | None:
    """Оценка прибыли при покупке сегодня и удержании до оферты/погашения."""
    if lots < 1 or bond.dirty_price_rub is None or bond.dirty_price_rub <= 0:
        return None

    end_date = _hold_end_date(bond, today)
    if end_date is None:
        return None

    position = position_from_bond(bond, lots=lots, purchase_date=today)
    invested = position.purchase_amount_rub
    coupon_income = _coupon_income_gross(position, end_date)
    redemption = _redemption_amount_gross(position, end_date)
    profit = coupon_income + redemption - invested
    hold_days = (end_date - today).days
    yield_pct = (profit / invested * 100.0) if invested > 0 else None

    return BondHoldResult(
        secid=bond.secid,
        name=bond.name,
        lots=lots,
        invested_rub=round(invested, 2),
        coupon_income_rub=round(coupon_income, 2),
        redemption_rub=round(redemption, 2),
        profit_rub=round(profit, 2),
        hold_days=hold_days,
        yield_pct=round(yield_pct, 2) if yield_pct is not None else None,
    )


def calculate_portfolio_budget(
    bonds: list[BondRecord],
    *,
    budget_rub: float,
    today: date,
) -> PortfolioHoldResult:
    """Распределить бюджет поровну и посчитать удержание по каждой бумаге."""
    if not bonds or budget_rub <= 0:
        return PortfolioHoldResult(
            positions=[],
            total_invested_rub=0.0,
            total_profit_rub=0.0,
            portfolio_yield_pct=None,
        )

    share = budget_rub / len(bonds)
    positions: list[BondHoldResult] = []
    total_invested = 0.0
    total_profit = 0.0

    for bond in bonds:
        if bond.dirty_price_rub is None or bond.dirty_price_rub <= 0:
            continue
        lot_cost = bond.dirty_price_rub * bond.lot_size
        lots = max(1, int(share / lot_cost))
        hold = calculate_bond_hold(bond, lots=lots, today=today)
        if hold is None:
            continue
        positions.append(hold)
        total_invested += hold.invested_rub
        total_profit += hold.profit_rub

    portfolio_yield = (total_profit / total_invested * 100.0) if total_invested > 0 else None
    return PortfolioHoldResult(
        positions=positions,
        total_invested_rub=round(total_invested, 2),
        total_profit_rub=round(total_profit, 2),
        portfolio_yield_pct=round(portfolio_yield, 2) if portfolio_yield is not None else None,
    )
