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
from bond_monitor.domain.portfolio.auto_compose import auto_compose
from bond_monitor.domain.trading.policies import (
    buy_limit_price_buffer,
    suggested_buy_limit_price_pct,
)

# При top-up ≥ N× от initial_amount пересобираем целевую структуру (как auto_compose).
LARGE_TOP_UP_RATIO_THRESHOLD = 2.0


def top_up_total_budget_rub(portfolio: Portfolio, top_up_amount_rub: float) -> float:
    """Полный бюджет портфеля для расчёта потолков при top-up."""
    return portfolio.initial_amount_rub + top_up_amount_rub


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
    3. Считаем «полный» бюджет для расчёта потолков через
       :func:`top_up_total_budget_rub` (без двойного учёта кэша).
    3b. Если ``top_up / initial ≥ LARGE_TOP_UP_RATIO_THRESHOLD`` — целевая
       структура как у ``auto_compose`` на полный бюджет (ребалансировка).
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

    total_budget = top_up_total_budget_rub(portfolio, top_up_amount_rub)
    if (
        portfolio.initial_amount_rub > 0
        and top_up_amount_rub / portfolio.initial_amount_rub >= LARGE_TOP_UP_RATIO_THRESHOLD
    ):
        return _distribute_top_up_rebalance(
            portfolio=portfolio,
            universe=scored,
            top_up_amount_rub=top_up_amount_rub,
            total_budget=total_budget,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
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
        lots_basis = p.lots
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


def _distribute_top_up_rebalance(
    *,
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    top_up_amount_rub: float,
    total_budget: float,
    today: date,
    key_rate: float,
    tax_rate: float,
) -> tuple[list[TopUpAllocation], list[str]]:
    """Распределить крупный top-up по целевой структуре ``auto_compose`` на полный бюджет."""
    notes: list[str] = [
        f"Крупное пополнение (≥ {LARGE_TOP_UP_RATIO_THRESHOLD:.0f}× от стартового бюджета) — "
        "пересборка целевой диверсификации."
    ]
    target_positions, _, compose_notes = auto_compose(
        initial_amount=total_budget,
        universe=universe,
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        api_trade_only=portfolio.api_trade_only,
    )
    notes.extend(compose_notes)
    if not target_positions:
        notes.append("Top-up не распределён: не удалось построить целевую структуру.")
        return [], notes

    target_lots_by_isin = {p.isin: p.lots for p in target_positions}
    current_lots_by_isin: dict[str, int] = {}
    for p in open_positions(portfolio.positions):
        lots_basis = p.lots
        current_lots_by_isin[p.isin] = current_lots_by_isin.get(p.isin, 0) + lots_basis

    universe_by_isin = {b.isin: b for b in universe}
    allocations: list[TopUpAllocation] = []
    remaining = top_up_amount_rub
    buffer = buy_limit_price_buffer(portfolio.account_kind)

    def _allocate_isin(isin: str, target_lots: int) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        bond = universe_by_isin.get(isin)
        if bond is None:
            return
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost <= 0:
            return
        needed_lots = max(0, target_lots - current_lots_by_isin.get(isin, 0))
        if needed_lots < 1:
            return
        lots = min(needed_lots, int(remaining // lot_cost))
        if lots < 1:
            return
        cost = lots * lot_cost
        last_price = bond.last_price if bond.last_price is not None else 100.0
        allocations.append(
            TopUpAllocation(
                isin=bond.isin,
                figi=bond.figi or None,
                name=bond.name,
                lots=lots,
                suggested_price_pct=float(
                    suggested_buy_limit_price_pct(last_price, buffer)
                ),
                estimated_amount_rub=cost,
                is_existing_position=isin in current_lots_by_isin,
            )
        )
        current_lots_by_isin[isin] = current_lots_by_isin.get(isin, 0) + lots
        remaining -= cost

    existing_isins = set(current_lots_by_isin)
    new_targets = [isin for isin in target_lots_by_isin if isin not in existing_isins]
    existing_targets = [isin for isin in target_lots_by_isin if isin in existing_isins]
    for isin in new_targets:
        _allocate_isin(isin, target_lots_by_isin[isin])
    for isin in existing_targets:
        _allocate_isin(isin, target_lots_by_isin[isin])

    if not allocations:
        notes.append("Top-up не распределён: нет подходящих бумаг или сумма слишком мала.")
        return [], notes

    distributed = top_up_amount_rub - remaining
    notes.append(
        f"Распределено {distributed:,.0f} ₽ из {top_up_amount_rub:,.0f} ₽ по "
        f"{len(allocations)} бумагам. Остаток: {remaining:,.0f} ₽."
    )
    return allocations, notes
