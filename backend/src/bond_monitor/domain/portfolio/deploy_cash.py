"""Unified cash deployment for plan simulation and trading advisory."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.auto_compose import (
    BuyAllocation,
    auto_compose,
    compose_buy_allocations,
    sweep_remaining_cash,
)
from bond_monitor.domain.portfolio.models import PortfolioPosition, PositionSourceType, RiskProfile
from bond_monitor.domain.portfolio.plan_models import MAX_AUTO_POSITIONS
from bond_monitor.domain.portfolio.policies import DEFAULT_DURATION_POLICY, DurationPolicy
from bond_monitor.domain.portfolio.position_factory import position_from_bond
from bond_monitor.domain.portfolio.reinvestment import validate_replacement_bond
from bond_monitor.domain.portfolio.selection import has_usable_price
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.trading.policies import (
    buy_limit_price_buffer,
    suggested_buy_limit_price_pct,
)


def max_affordable_lots(
    bond: BondRecord,
    *,
    budget_rub: float,
    purchase_date: date,
    source: PositionSourceType,
) -> int:
    """Макс. лоты, которые укладываются в ``budget_rub`` с учётом dirty-цены."""
    lot_cost = bond.price_per_lot_rub or 0.0
    if lot_cost <= 0 or budget_rub + 0.01 < lot_cost:
        return 0
    lots = int(budget_rub // lot_cost)
    while lots > 0:
        phantom = position_from_bond(
            bond,
            lots=lots,
            purchase_date=purchase_date,
            source=source,
        )
        if phantom.purchase_amount_rub <= budget_rub + 0.01:
            return lots
        lots -= 1
    return 0


def _positions_to_allocations(
    target_positions: Sequence[PortfolioPosition],
    *,
    universe_by_isin: dict[str, BondRecord],
    existing_isins: set[str],
    account_kind: AccountKind | None,
) -> list[BuyAllocation]:
    buffer = buy_limit_price_buffer(account_kind)
    allocations: list[BuyAllocation] = []
    for position in target_positions:
        bond = universe_by_isin.get(position.isin)
        if bond is None or position.lots < 1:
            continue
        last_price = bond.last_price if bond.last_price is not None else 100.0
        allocations.append(
            BuyAllocation(
                isin=bond.isin,
                figi=bond.figi or None,
                name=bond.name,
                lots=position.lots,
                suggested_price_pct=float(
                    suggested_buy_limit_price_pct(last_price, buffer)
                ),
                estimated_amount_rub=position.purchase_amount_rub,
                is_existing_position=position.isin in existing_isins,
            )
        )
    return allocations


def _merge_allocation_lots(allocations: list[BuyAllocation]) -> list[BuyAllocation]:
    merged: dict[str, BuyAllocation] = {}
    order: list[str] = []
    for item in allocations:
        existing = merged.get(item.isin)
        if existing is None:
            merged[item.isin] = BuyAllocation(
                isin=item.isin,
                figi=item.figi,
                name=item.name,
                lots=item.lots,
                suggested_price_pct=item.suggested_price_pct,
                estimated_amount_rub=item.estimated_amount_rub,
                is_existing_position=item.is_existing_position,
            )
            order.append(item.isin)
            continue
        merged[item.isin] = BuyAllocation(
            isin=existing.isin,
            figi=existing.figi,
            name=existing.name,
            lots=existing.lots + item.lots,
            suggested_price_pct=existing.suggested_price_pct,
            estimated_amount_rub=existing.estimated_amount_rub + item.estimated_amount_rub,
            is_existing_position=existing.is_existing_position or item.is_existing_position,
        )
    return [merged[isin] for isin in order]


def deploy_cash(
    *,
    cash_rub: float,
    current_lots_by_isin: dict[str, int],
    universe: Sequence[BondRecord],
    profile: RiskProfile,
    horizon_date: date,
    as_of_date: date,
    key_rate: float,
    tax_rate: float,
    api_trade_only: bool,
    account_kind: AccountKind | None,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
    confirmed_isin: str | None = None,
    reinvest_source: PositionSourceType = PositionSourceType.REINVEST_MATURITY,
) -> tuple[list[BuyAllocation], float, list[str]]:
    """Развернуть весь доступный кэш: единая точка для плана и advisory."""
    notes: list[str] = []
    if cash_rub <= 0:
        return [], 0.0, ["Сумма к развёртыванию ≤ 0 — нечего распределять."]

    universe_by_isin = {bond.isin: bond for bond in universe}
    existing_isins = set(current_lots_by_isin)

    if confirmed_isin:
        bond = universe_by_isin.get(confirmed_isin)
        if bond is None or not has_usable_price(bond):
            notes.append(
                f"Бумага {confirmed_isin} недоступна или без рыночной цены."
            )
            return [], cash_rub, notes
        invalid = validate_replacement_bond(
            bond,
            slot_purchase_date=as_of_date,
            horizon=horizon_date,
        )
        if invalid is not None:
            notes.append(f"Подтверждённая замена отклонена: {invalid}")
            return [], cash_rub, notes
        lots = max_affordable_lots(
            bond,
            budget_rub=cash_rub,
            purchase_date=as_of_date,
            source=reinvest_source,
        )
        if lots < 1:
            notes.append("Недостаточно кэша на 1 лот подтверждённой замены.")
            return [], cash_rub, notes
        phantom = position_from_bond(
            bond,
            lots=lots,
            purchase_date=as_of_date,
            source=reinvest_source,
        )
        buffer = buy_limit_price_buffer(account_kind)
        last_price = bond.last_price if bond.last_price is not None else 100.0
        spent = phantom.purchase_amount_rub
        remaining = max(0.0, cash_rub - spent)
        allocations = [
            BuyAllocation(
                isin=bond.isin,
                figi=bond.figi or None,
                name=bond.name,
                lots=lots,
                suggested_price_pct=float(
                    suggested_buy_limit_price_pct(last_price, buffer)
                ),
                estimated_amount_rub=spent,
                is_existing_position=bond.isin in existing_isins,
            )
        ]
        if remaining > 0:
            extra, rem2, extra_notes = deploy_cash(
                cash_rub=remaining,
                current_lots_by_isin={
                    **current_lots_by_isin,
                    bond.isin: current_lots_by_isin.get(bond.isin, 0) + lots,
                },
                universe=universe,
                profile=profile,
                horizon_date=horizon_date,
                as_of_date=as_of_date,
                key_rate=key_rate,
                tax_rate=tax_rate,
                api_trade_only=api_trade_only,
                account_kind=account_kind,
                duration_policy=duration_policy,
                confirmed_isin=None,
                reinvest_source=reinvest_source,
            )
            notes.extend(extra_notes)
            allocations = _merge_allocation_lots(allocations + extra)
            remaining = rem2
        notes.append(
            f"Распределено {cash_rub - remaining:,.0f} ₽ из {cash_rub:,.0f} ₽."
        )
        return allocations, remaining, notes

    if len(existing_isins) >= MAX_AUTO_POSITIONS:
        holdings_value = sum(
            (universe_by_isin[isin].price_per_lot_rub or 0.0) * lots
            for isin, lots in current_lots_by_isin.items()
            if isin in universe_by_isin
        )
        allocations, compose_notes = compose_buy_allocations(
            total_budget_rub=holdings_value + cash_rub,
            cash_to_deploy_rub=cash_rub,
            current_lots_by_isin=current_lots_by_isin,
            universe=universe,
            profile=profile,
            horizon_date=horizon_date,
            today=as_of_date,
            key_rate=key_rate,
            tax_rate=tax_rate,
            api_trade_only=api_trade_only,
            account_kind=account_kind,
            duration_policy=duration_policy,
        )
        notes.extend(compose_notes)
        spent = sum(item.estimated_amount_rub for item in allocations)
        remaining = max(0.0, cash_rub - spent)
        if remaining > 0:
            swept, sweep_notes = sweep_remaining_cash(
                remaining_cash_rub=remaining,
                current_lots_by_isin={
                    **current_lots_by_isin,
                    **{a.isin: current_lots_by_isin.get(a.isin, 0) + a.lots for a in allocations},
                },
                universe=universe,
                profile=profile,
                horizon_date=horizon_date,
                as_of_date=as_of_date,
                key_rate=key_rate,
                tax_rate=tax_rate,
                api_trade_only=api_trade_only,
                account_kind=account_kind,
                duration_policy=duration_policy,
                total_budget_rub=holdings_value + cash_rub,
            )
            notes.extend(sweep_notes)
            allocations = _merge_allocation_lots(allocations + swept)
            spent = sum(item.estimated_amount_rub for item in allocations)
            remaining = max(0.0, cash_rub - spent)
        notes.append(
            f"Распределено {cash_rub - remaining:,.0f} ₽ из {cash_rub:,.0f} ₽ "
            f"по {len(allocations)} бумагам. Остаток: {remaining:,.0f} ₽."
        )
        return allocations, remaining, notes

    target_positions, remaining, compose_notes = auto_compose(
        initial_amount=cash_rub,
        universe=universe,
        profile=profile,
        horizon_date=horizon_date,
        today=as_of_date,
        key_rate=key_rate,
        tax_rate=tax_rate,
        api_trade_only=api_trade_only,
        duration_policy=duration_policy,
    )
    notes.extend(compose_notes)
    allocations = _positions_to_allocations(
        target_positions,
        universe_by_isin=universe_by_isin,
        existing_isins=existing_isins,
        account_kind=account_kind,
    )
    if remaining > 0 and allocations:
        swept, sweep_notes = sweep_remaining_cash(
            remaining_cash_rub=remaining,
            current_lots_by_isin={
                **current_lots_by_isin,
                **{a.isin: current_lots_by_isin.get(a.isin, 0) + a.lots for a in allocations},
            },
            universe=universe,
            profile=profile,
            horizon_date=horizon_date,
            as_of_date=as_of_date,
            key_rate=key_rate,
            tax_rate=tax_rate,
            api_trade_only=api_trade_only,
            account_kind=account_kind,
            duration_policy=duration_policy,
            total_budget_rub=cash_rub,
        )
        notes.extend(sweep_notes)
        allocations = _merge_allocation_lots(allocations + swept)
        spent = sum(item.estimated_amount_rub for item in allocations)
        remaining = max(0.0, cash_rub - spent)

    if not allocations:
        notes.append("Кэш не распределён: не удалось построить целевую структуру.")
        return [], cash_rub, notes

    notes.append(
        f"Распределено {cash_rub - remaining:,.0f} ₽ из {cash_rub:,.0f} ₽ "
        f"по {len(allocations)} бумагам. Остаток: {remaining:,.0f} ₽."
    )
    return allocations, remaining, notes
