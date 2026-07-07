"""Ограничения свободного кэша в режиме торговли."""

from __future__ import annotations

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, order_amount_rub
from bond_monitor.domain.trading.pending_operations import pending_top_up_lots_for_isin
from bond_monitor.domain.trading.reconciler import TOP_UP_COST_BUFFER


def _position_unit_cost_rub(
    position: PortfolioPosition,
    universe_by_isin: dict[str, BondRecord],
) -> float:
    bond = universe_by_isin.get(position.isin)
    if bond is not None and bond.dirty_price_rub:
        return float(bond.dirty_price_rub)
    return position.purchase_dirty_price_rub


def estimate_pending_purchase_commitment_rub(
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> float:
    """Сумма уже запланированных, но не исполненных покупок на счёте."""
    if not portfolio.is_trading:
        return 0.0

    total = 0.0
    for op in portfolio.pending_operations:
        if op.kind != "top_up_buy":
            continue
        if op.estimated_amount_rub is not None:
            total += op.estimated_amount_rub
            continue
        bond = universe_by_isin.get(op.isin)
        lot_size = bond.lot_size if bond else 1
        face_value = bond.face_value if bond else 1000.0
        price_pct = op.suggested_price_pct or (bond.last_price if bond else 100.0)
        if price_pct is not None:
            aci_rub = (bond.accrued_interest or 0.0) if bond else 0.0
            total += float(
                order_amount_rub(
                    price_pct=PriceUnitPct(float(price_pct)),
                    face_value=face_value,
                    lot_size=lot_size,
                    lots=Lots(op.lots),
                    aci_rub=aci_rub,
                )
            )

    for position in portfolio.positions:
        if position.actual_lots is None:
            continue
        top_up_lots = pending_top_up_lots_for_isin(portfolio, position.isin)
        gap_lots = position.lots - position.actual_lots - top_up_lots
        if gap_lots <= 0:
            continue
        unit_cost = _position_unit_cost_rub(position, universe_by_isin)
        total += gap_lots * position.lot_size * unit_cost

    return round(total, 2)


def available_cash_for_new_purchases_rub(
    money_rub: float,
    portfolio: Portfolio,
    universe_by_isin: dict[str, BondRecord],
) -> float:
    """Свободный кэш после резерва под уже запланированные покупки."""
    safe_limit = max(0.0, money_rub * (1.0 - TOP_UP_COST_BUFFER))
    committed = estimate_pending_purchase_commitment_rub(portfolio, universe_by_isin)
    return max(0.0, round(safe_limit - committed, 2))


def initial_buy_gap_lots(
    portfolio: Portfolio,
    position: PortfolioPosition,
) -> int:
    """Лоты стартовой покупки, ещё не покрытые top_up_buy pending."""
    if not portfolio.is_trading or position.actual_lots is None:
        return 0
    remaining = position.lots - position.actual_lots
    remaining -= pending_top_up_lots_for_isin(portfolio, position.isin)
    return max(0, remaining)


__all__ = [
    "available_cash_for_new_purchases_rub",
    "estimate_pending_purchase_commitment_rub",
    "initial_buy_gap_lots",
]
