"""Параметры торговой логики (лимитные заявки, буферы цены)."""

from __future__ import annotations

from bond_monitor.domain.portfolio.models import AccountKind
from bond_monitor.domain.shared.money import PriceUnitPct

# Буфер к рыночной цене для пассивной лимитной покупки (last_price × (1 + buffer)).
BUY_LIMIT_PRICE_BUFFER_SANDBOX: float = 0.005  # +0.5% — песочница
BUY_LIMIT_PRICE_BUFFER_PRODUCTION: float = 0.002  # +0.2% — боевой контур


def buy_limit_price_buffer(account_kind: AccountKind | None) -> float:
    """Буфер лимитной цены покупки в зависимости от контура T-Invest."""
    if account_kind == AccountKind.PRODUCTION:
        return BUY_LIMIT_PRICE_BUFFER_PRODUCTION
    return BUY_LIMIT_PRICE_BUFFER_SANDBOX


def format_buy_limit_buffer_label(buffer: float) -> str:
    """Человекочитаемая подпись буфера для reason в UI, напр. «0.5%»."""
    return f"{buffer * 100:g}%"


def suggested_buy_limit_price_pct(base_pct: float, buffer: float) -> PriceUnitPct:
    """Рекомендуемая лимитная цена покупки: рынок + buffer."""
    return PriceUnitPct(round(base_pct * (1 + buffer), 4))
