"""Redemption and put-offer proceeds for portfolio positions."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import PortfolioPosition


def price_gain_total(position: PortfolioPosition) -> float:
    """Положительная разница «номинал − чистая цена покупки» × количество."""
    clean_at_purchase = position.purchase_clean_price_pct / 100.0 * position.face_value
    diff = position.face_value - clean_at_purchase
    return diff * position.bonds_count


def net_redemption_amount(
    position: PortfolioPosition,
    tax_rate: float,
    *,
    is_put: bool = False,
) -> float:
    """Сумма к получению при погашении/пут-оферте после НДФЛ на курсовую разницу."""
    if is_put:
        price_pct = position.offer_price_pct or 100.0
        redemption_per_bond = position.face_value * (price_pct / 100.0)
    else:
        redemption_per_bond = position.face_value
    gross = redemption_per_bond * position.bonds_count
    clean_at_purchase = position.purchase_clean_price_pct / 100.0 * position.face_value
    taxable_gain = max(0.0, (redemption_per_bond - clean_at_purchase) * position.bonds_count)
    tax = taxable_gain * tax_rate
    return gross - tax
