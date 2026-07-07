"""Top-up cash distribution across portfolio positions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.portfolio.plan_models import (
    MAX_AUTO_POSITIONS,
    MAX_POSITION_SHARE,
    MIN_AUTO_POSITIONS,
    MIN_POSITION_AMOUNT_RUB,
    MIN_POSITION_SHARE,
    TARGET_POSITION_SHARE,
)
from bond_monitor.domain.portfolio.position_status import open_positions
from bond_monitor.domain.portfolio.reinvestment import selection_context
from bond_monitor.domain.portfolio.selection import select_ranked_bonds
from bond_monitor.domain.trading.policies import (
    buy_limit_price_buffer,
    suggested_buy_limit_price_pct,
)


@dataclass
class TopUpAllocation:
    """Одна аллокация при распределении top-up свободного кэша.

    ``is_existing_position`` — для UI-бейджа «уже в портфеле» vs «новая
    позиция». Не влияет на логику покупки.

    ``estimated_amount_rub`` — ожидаемая сумма заявки (``lots × lot_size ×
    dirty_price``).
    """

    isin: str
    figi: str | None
    name: str
    lots: int
    suggested_price_pct: float
    estimated_amount_rub: float
    is_existing_position: bool


def distribute_top_up(
    *,
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    top_up_amount_rub: float,
    today: date,
    key_rate: float,
    tax_rate: float,
) -> tuple[list[TopUpAllocation], list[str]]:
    """Распределить top-up по бумагам согласно стратегии портфеля.

    Алгоритм (см. AGENTS.md «Режим торговли → Top-up»):

    1. Фильтруем universe через `risk_profile_filter(portfolio.risk_profile)`
       + `put_offer_buy_blocked(today)`.
    2. Сортируем по `score_bonds_for_profile(profile)`.
    3. Считаем «полный» бюджет для расчёта потолков:
       ``total_budget = initial_amount + acknowledged_top_ups + new_top_up``.
    4. Идём по топу скоринга, для каждой бумаги:
       a. Текущая стоимость в портфеле (если уже есть): сумма
          ``lots × lot_size × current_price`` совпадающего ISIN.
       b. Потолок: ``cap = total_budget × MAX_POSITION_SHARE``.
       c. Доступная «дыра»: ``gap = max(cap − current_value, 0)``.
       d. Покупаем минимум из {target_per_position, gap, top_up_remaining}
          лотов (округление вниз).
       e. Уменьшаем `top_up_remaining`.
    5. Останавливаемся когда `top_up_remaining < min(lot_cost)` или
       достигнут `MAX_AUTO_POSITIONS`.

    Не продаём, не нарушаем `MAX_POSITION_SHARE`. Идемпотентно (не
    мутирует portfolio).

    Returns:
        (allocations, notes) — список покупок и пояснения для UI.
    """
    notes: list[str] = []
    if top_up_amount_rub <= 0:
        return [], ["Сумма top-up ≤ 0 — нечего распределять."]

    selection_ctx = selection_context(
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        purchase_date=today,
        api_trade_only=portfolio.api_trade_only,
    )
    scored = select_ranked_bonds(
        universe,
        selection_ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
    ).bonds
    if not scored:
        return [], [
            "Под текущий профиль и горизонт нет ни одной подходящей бумаги — top-up не распределён."
        ]

    total_budget = (
        portfolio.initial_amount_rub + portfolio.acknowledged_top_ups_rub + top_up_amount_rub
    )
    cap_per_position = total_budget * MAX_POSITION_SHARE
    target_per_position = total_budget / max(MIN_AUTO_POSITIONS, round(1.0 / TARGET_POSITION_SHARE))
    min_per_position = max(MIN_POSITION_AMOUNT_RUB, total_budget * MIN_POSITION_SHARE)

    # Текущее распределение по ISIN (оценка по рыночной стоимости позиций).
    current_value_by_isin: dict[str, float] = {}
    for p in open_positions(portfolio.positions):
        bond = next((b for b in scored if b.isin == p.isin), None)
        unit_cost = bond.price_per_lot_rub if bond and bond.price_per_lot_rub else 0.0
        if unit_cost <= 0:
            unit_cost = (
                p.purchase_dirty_price_rub * p.lot_size if p.purchase_dirty_price_rub else 0.0
            )
        lots_basis = p.actual_lots if p.actual_lots is not None and portfolio.is_trading else p.lots
        market_value = lots_basis * unit_cost if unit_cost > 0 else p.purchase_amount_rub
        current_value_by_isin[p.isin] = current_value_by_isin.get(p.isin, 0.0) + market_value

    allocations: list[TopUpAllocation] = []
    remaining = top_up_amount_rub
    existing_count = len({p.isin for p in open_positions(portfolio.positions)})

    for bond in scored:
        if remaining < min_per_position and existing_count + len(allocations) >= MIN_AUTO_POSITIONS:
            break
        if existing_count + len(allocations) >= MAX_AUTO_POSITIONS:
            notes.append(
                f"Достигнут лимит {MAX_AUTO_POSITIONS} позиций — остаток "
                f"{remaining:,.0f} ₽ не распределён."
            )
            break
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost <= 0:
            continue
        if lot_cost > cap_per_position:
            continue

        current_value = current_value_by_isin.get(bond.isin, 0.0)
        gap = max(cap_per_position - current_value, 0.0)
        if gap < lot_cost:
            continue
        # Максимум лотов по трём ограничениям: остаток top-up, доступная
        # «дыра» до потолка, целевой target (для равномерности).
        max_lots_by_remaining = int(remaining // lot_cost)
        max_lots_by_gap = int(gap // lot_cost)
        max_lots_by_target = max(1, int(target_per_position // lot_cost))
        lots = min(max_lots_by_remaining, max_lots_by_gap, max_lots_by_target)
        if lots < 1:
            continue
        cost = lots * lot_cost
        if cost < min_per_position and current_value < min_per_position:
            # Микро-аллокация в новую позицию — пропустим, чтобы не
            # плодить огрызки.
            continue

        is_existing = bond.isin in current_value_by_isin
        last_price = bond.last_price if bond.last_price is not None else 100.0
        suggested = float(
            suggested_buy_limit_price_pct(
                last_price, buy_limit_price_buffer(portfolio.account_kind)
            )
        )
        allocations.append(
            TopUpAllocation(
                isin=bond.isin,
                figi=bond.figi or None,
                name=bond.name,
                lots=lots,
                suggested_price_pct=suggested,
                estimated_amount_rub=cost,
                is_existing_position=is_existing,
            )
        )
        current_value_by_isin[bond.isin] = current_value + cost
        remaining -= cost

    if not allocations:
        notes.append("Top-up не распределён: нет подходящих бумаг или сумма слишком мала.")
        return [], notes

    distributed = top_up_amount_rub - remaining
    notes.append(
        f"Распределено {distributed:,.0f} ₽ из {top_up_amount_rub:,.0f} ₽ по "
        f"{len(allocations)} бумагам. Остаток: {remaining:,.0f} ₽."
    )
    return allocations, notes
