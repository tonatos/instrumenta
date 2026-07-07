"""Ограничения свободного кэша в режиме торговли."""

from __future__ import annotations

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, order_amount_rub
from bond_monitor.domain.trading.pending_operations import pending_top_up_lots_for_isin
from bond_monitor.domain.trading.reconciler import TOP_UP_COST_BUFFER


def available_cash_for_new_purchases_rub(
    money_rub: float,
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> float:
    """Кэш для авто-распределения top-up: остаток на счёте минус уже созданные top_up_buy."""
    if not portfolio.is_trading:
        return max(0.0, money_rub)

    reserved = 0.0
    for op in portfolio.pending_operations:
        if op.kind != "top_up_buy":
            continue
        if op.estimated_amount_rub is not None:
            reserved += op.estimated_amount_rub
            continue
        bond = universe_by_isin.get(op.isin)
        price_pct = op.suggested_price_pct or (bond.last_price if bond else 100.0)
        if price_pct is None:
            continue
        reserved += float(
            order_amount_rub(
                price_pct=PriceUnitPct(float(price_pct)),
                face_value=bond.face_value if bond else 1000.0,
                lot_size=bond.lot_size if bond else 1,
                lots=Lots(op.lots),
                aci_rub=(bond.accrued_interest or 0.0) if bond else 0.0,
            )
        )

    safe_limit = max(0.0, money_rub * (1.0 - TOP_UP_COST_BUFFER))
    return max(0.0, round(safe_limit - reserved, 2))


def initial_buy_gap_lots(
    portfolio: Portfolio,
    position: PortfolioPosition,
) -> int:
    """Лоты, которые ещё не на счёте и не покрыты top_up_buy pending."""
    if not portfolio.is_trading or position.actual_lots is None:
        return 0
    remaining = position.lots - position.actual_lots
    remaining -= pending_top_up_lots_for_isin(portfolio, position.isin)
    return max(0, remaining)


__all__ = [
    "available_cash_for_new_purchases_rub",
    "initial_buy_gap_lots",
]
