"""
Бизнес-логика модуля «Портфель» — публичный фасад.

Реализация разбита по подмодулям:

* :mod:`plan_models` — типы плана и константы политик.
* :mod:`reinvestment` — слоты реинвестиции и подбор замен.
* :mod:`auto_compose` — автосостав портфеля и развёртывание доступного кэша.
* :mod:`plan_builder` — построение cashflow-плана.
"""

from __future__ import annotations

from bond_monitor.domain.portfolio.auto_compose import (
    BuyAllocation,
    auto_compose,
    compose_buy_allocations,
    format_share,
)
from bond_monitor.domain.portfolio.deploy_cash import deploy_cash, max_affordable_lots
from bond_monitor.domain.portfolio.cashflow import CashflowEvent, merge_cashflow_events
from bond_monitor.domain.portfolio.plan_builder import _net_redemption_amount, build_plan
from bond_monitor.domain.portfolio.plan_models import (
    HeldPositionAtHorizon,
    PortfolioPlan,
    PortfolioValuePoint,
    UpcomingPutOffer,
)
from bond_monitor.domain.portfolio.position_factory import position_from_bond
from bond_monitor.domain.portfolio.reinvestment import (
    clear_downstream_slot_overrides,
    enrich_reinvestment_slot,
    prune_stale_slot_overrides,
    select_replacement,
    validate_replacement_bond,
    validate_slot_replacement,
)
from bond_monitor.domain.portfolio.selection import (
    api_tradable_filter,
    portfolio_universe_filter,
    risk_profile_filter,
)
# Backward compatibility for tests importing private merge helper from planner.
_merge_cashflow_events = merge_cashflow_events

# Backward compatibility for tests importing private helpers from planner.

__all__ = [
    "CashflowEvent",
    "HeldPositionAtHorizon",
    "PortfolioPlan",
    "PortfolioValuePoint",
    "BuyAllocation",
    "UpcomingPutOffer",
    "api_tradable_filter",
    "auto_compose",
    "build_plan",
    "clear_downstream_slot_overrides",
    "compose_buy_allocations",
    "deploy_cash",
    "enrich_reinvestment_slot",
    "format_share",
    "max_affordable_lots",
    "portfolio_universe_filter",
    "position_from_bond",
    "prune_stale_slot_overrides",
    "risk_profile_filter",
    "select_replacement",
    "validate_replacement_bond",
    "validate_slot_replacement",
]
