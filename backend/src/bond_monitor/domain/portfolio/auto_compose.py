"""Initial portfolio auto-composition."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import PortfolioPosition, RiskProfile
from bond_monitor.domain.portfolio.plan_models import (
    MAX_AUTO_POSITIONS,
    MAX_POSITION_SHARE,
    MIN_AUTO_POSITIONS,
    MIN_POSITION_AMOUNT_RUB,
    MIN_POSITION_SHARE,
    TARGET_POSITION_SHARE,
)
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_DURATION_POLICY,
    DurationPolicy,
)
from bond_monitor.domain.portfolio.position_factory import position_from_bond
from bond_monitor.domain.portfolio.reinvestment import selection_context
from bond_monitor.domain.portfolio.selection import select_ranked_bonds
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.domain.trading.policies import (
    buy_limit_price_buffer,
    suggested_buy_limit_price_pct,
)


def _apply_duration_guardrail(
    bonds: list[BondRecord],
    duration_policy: DurationPolicy,
    notes: list[str],
) -> list[BondRecord]:
    """Отсечь бумаги длиннее лимита дюрации (риск-контур).

    Если каждая включённая бумага ≤ ``max_weighted_duration_years``, то и
    средневзвешенная дюрация корзины ≤ лимита — достаточное условие без
    пост-фактум пересборки. Бумаги без данных о дюрации не отсекаются.
    """
    limit = duration_policy.max_weighted_duration_years
    if limit is None:
        return bonds
    kept = [b for b in bonds if b.duration_years is None or b.duration_years <= limit]
    dropped = len(bonds) - len(kept)
    if dropped > 0:
        notes.append(
            f"Гардрейл по дюрации: исключено {dropped} бумаг(и) с дюрацией "
            f"> {limit:.1f} г."
        )
    return kept


def auto_compose(
    *,
    initial_amount: float,
    universe: Sequence[BondRecord],
    profile: RiskProfile,
    horizon_date: date,
    today: date,
    key_rate: float,
    tax_rate: float,
    api_trade_only: bool = True,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> tuple[list[PortfolioPosition], float, list[str]]:
    """Сформировать стартовый набор позиций под выбранный профиль и бюджет.

    Принципы распределения:

    1. **Диверсификация:** стремимся к ``MIN_AUTO_POSITIONS … MAX_AUTO_POSITIONS``
       позициям. Базовое число — ``initial_amount / TARGET_POSITION_SHARE``,
       но не меньше ``MIN_AUTO_POSITIONS`` и не больше ``MAX_AUTO_POSITIONS``.
    2. **Равномерность:** целевая сумма одной позиции
       ``target_per_position = initial_amount / target_count``. Алгоритм
       пытается покупать ровно столько лотов, чтобы вложенная сумма
       была близка к ``target_per_position``. Жёсткий потолок —
       ``MAX_POSITION_SHARE`` бюджета.
    3. **Отсутствие микропозиций:** минимум вложений в одну бумагу —
       ``max(MIN_POSITION_AMOUNT_RUB, MIN_POSITION_SHARE × бюджет)``.
       Если кандидат не помещается в этот минимум по 1 лоту — пропускаем
       (либо в конце пытаемся «добить» оставшимся бюджетом, см. шаг 5).
    4. **Профильный скор:** кандидаты упорядочены по
       :func:`score_bonds_for_profile`. Для AGGRESSIVE веса смещены в сторону
       YTM — это и есть «оптимизация по доходности», о которой говорил
       пользователь.
    5. **Доп-пополнение:** после первого прохода, если остался кэш ≥
       ``min_per_position``, пробуем увеличить позиции (по 1 лоту,
       начиная с самых прибыльных), не превышая ``MAX_POSITION_SHARE``.
       Так избегаем «огрызков» в конце.

    Returns:
        (positions, leftover_cash_rub, notes) — список купленных позиций,
        неинвестированный остаток (он попадёт в ``cash_balance_rub`` портфеля)
        и пояснения для UI.
    """
    notes: list[str] = []
    if initial_amount <= 0:
        return [], 0.0, ["Бюджет ≤ 0 — нечего распределять"]

    selection_ctx = selection_context(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=today,
        api_trade_only=api_trade_only,
    )
    selection = select_ranked_bonds(
        universe,
        selection_ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
        duration_policy=duration_policy,
    )
    scored = _apply_duration_guardrail(selection.bonds, duration_policy, notes)
    if not scored:
        notes.append(
            "Под выбранный профиль и горизонт не нашлось ни одной подходящей бумаги. "
            + (
                "Попробуйте отключить фильтр «только API-торгуемые» или "
                "расширьте горизонт / смягчите профиль."
                if api_trade_only
                else "Расширьте горизонт, смягчите профиль или обновите данные MOEX."
            )
        )
        return [], initial_amount, notes
    if selection.fallback_note:
        notes.append(selection.fallback_note)

    target_count = max(
        MIN_AUTO_POSITIONS,
        min(MAX_AUTO_POSITIONS, round(1.0 / TARGET_POSITION_SHARE)),
    )
    target_per_position = initial_amount / target_count
    max_per_position = initial_amount * MAX_POSITION_SHARE
    min_per_position = max(MIN_POSITION_AMOUNT_RUB, initial_amount * MIN_POSITION_SHARE)

    remaining = initial_amount
    positions: list[PortfolioPosition] = []
    bought_by_isin: dict[str, dict] = {}

    # Шаг 1: первый проход — каждая бумага получает ~target_per_position.
    for bond in scored:
        if remaining < min_per_position or len(positions) >= target_count:
            break
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost <= 0:
            continue

        # Скольки лотов хочется: ровно столько, чтобы вложить ~target.
        target_lots = max(1, round(target_per_position / lot_cost))
        cost_at_target = target_lots * lot_cost

        # Бумаги, у которых даже 1 лот не помещается в потолок 30% или в
        # минимальную позицию, — пропускаем. Это типично для дорогих
        # «джамбо»-выпусков с лотом 100 000+.
        if lot_cost > max_per_position:
            continue
        if cost_at_target < min_per_position:
            # Доразместим до min_per_position, если умещаемся в потолок.
            target_lots = int(min_per_position // lot_cost) + 1
            cost_at_target = target_lots * lot_cost
            if cost_at_target > max_per_position or cost_at_target > remaining:
                continue
        # Не превышаем потолок 30%.
        if cost_at_target > max_per_position:
            target_lots = int(max_per_position // lot_cost)
            cost_at_target = target_lots * lot_cost
        # Не превышаем оставшийся бюджет.
        if cost_at_target > remaining:
            target_lots = int(remaining // lot_cost)
            cost_at_target = target_lots * lot_cost
        if target_lots < 1 or cost_at_target < min_per_position:
            continue

        positions.append(position_from_bond(bond, lots=target_lots, purchase_date=today))
        bought_by_isin[bond.isin] = {"bond": bond, "lots": target_lots, "cost": cost_at_target}
        remaining -= cost_at_target

    # Шаг 2: добавочные лоты в уже купленные бумаги, чтобы съесть остаток.
    # Идём в порядке скоринга (самые прибыльные первыми) и докидываем по
    # одному лоту, пока остаток ≥ стоимости лота и доля не уперлась в
    # MAX_POSITION_SHARE.
    if remaining >= min_per_position:
        changed = True
        while changed and remaining > 0:
            changed = False
            for bond in scored:
                state = bought_by_isin.get(bond.isin)
                if state is None:
                    continue
                lot_cost = state["bond"].price_per_lot_rub or 0.0
                if lot_cost <= 0 or lot_cost > remaining:
                    continue
                if state["cost"] + lot_cost > max_per_position:
                    continue
                state["lots"] += 1
                state["cost"] += lot_cost
                remaining -= lot_cost
                changed = True
                if remaining < lot_cost:
                    break

        # Применяем накопленные доп-лоты к позициям.
        for pos in positions:
            state = bought_by_isin.get(pos.isin)
            if state is None or state["lots"] == pos.lots:
                continue
            new_lots = state["lots"]
            pos.lots = new_lots
            pos.purchase_amount_rub = pos.purchase_dirty_price_rub * new_lots * pos.lot_size

    # Шаг 3: если набрали меньше MIN_AUTO_POSITIONS и есть кэш — пробуем
    # добавить ещё одну бумагу (даже если она «дорогая» в смысле лота).
    if len(positions) < MIN_AUTO_POSITIONS and remaining >= min_per_position:
        for bond in scored:
            if bond.isin in bought_by_isin:
                continue
            lot_cost = bond.price_per_lot_rub or 0.0
            if lot_cost <= 0 or lot_cost > remaining or lot_cost > max_per_position:
                continue
            max_lots = min(
                int(remaining // lot_cost),
                int(max_per_position // lot_cost),
            )
            if max_lots < 1:
                continue
            cost = max_lots * lot_cost
            if cost < min_per_position:
                continue
            positions.append(position_from_bond(bond, lots=max_lots, purchase_date=today))
            bought_by_isin[bond.isin] = {"bond": bond, "lots": max_lots, "cost": cost}
            remaining -= cost
            if len(positions) >= MIN_AUTO_POSITIONS or remaining < min_per_position:
                break

    if not positions:
        notes.append(
            "Не нашлось бумаг, помещающихся в правила диверсификации (одна позиция "
            f"должна быть не меньше {min_per_position:,.0f} ₽ и не больше "
            f"{max_per_position:,.0f} ₽). Увеличьте бюджет или смягчите профиль."
        )
    else:
        notes.append(
            f"Распределение: {len(positions)} позиций по ~"
            f"{format_share(target_per_position, initial_amount)} бюджета каждая "
            f"(потолок {MAX_POSITION_SHARE * 100:.0f}%, минимум "
            f"{min_per_position:,.0f} ₽)."
        )
        if remaining >= min_per_position:
            notes.append(
                f"Остаток {remaining:,.0f} ₽ не вложен — недостаточно для очередной "
                "позиции по правилам диверсификации (можно добавить вручную "
                "через форму ниже)."
            )

    return positions, remaining, notes


def format_share(value: float, total: float) -> str:
    """Форматирование доли как ``18% (72 000 ₽)`` для пояснений."""
    if total <= 0:
        return f"{value:,.0f} ₽"
    pct = value / total * 100
    return f"{pct:.0f}% ({value:,.0f} ₽)"


@dataclass
class BuyAllocation:
    """Одна покупка при развёртывании доступного кэша по ``auto_compose``."""

    isin: str
    figi: str | None
    name: str
    lots: int
    suggested_price_pct: float
    estimated_amount_rub: float
    is_existing_position: bool


def _top_scored_existing_bonds(
    universe: Sequence[BondRecord],
    existing_isins: set[str],
    *,
    profile: RiskProfile,
    horizon_date: date,
    today: date,
    key_rate: float,
    tax_rate: float,
    api_trade_only: bool,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> list[BondRecord]:
    """Топ ``MAX_AUTO_POSITIONS`` держимых бумаг по скорингу."""
    selection_ctx = selection_context(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=today,
        api_trade_only=api_trade_only,
    )
    scored = select_ranked_bonds(
        universe,
        selection_ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
        duration_policy=duration_policy,
    ).bonds
    result: list[BondRecord] = []
    for bond in scored:
        if bond.isin not in existing_isins:
            continue
        result.append(bond)
        if len(result) >= MAX_AUTO_POSITIONS:
            break
    return result


def compose_buy_allocations(
    *,
    total_budget_rub: float,
    cash_to_deploy_rub: float,
    current_lots_by_isin: dict[str, int],
    universe: Sequence[BondRecord],
    profile: RiskProfile,
    horizon_date: date,
    today: date,
    key_rate: float,
    tax_rate: float,
    api_trade_only: bool,
    account_kind: AccountKind | None,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> tuple[list[BuyAllocation], list[str]]:
    """Развернуть доступный кэш по целевой структуре ``auto_compose``.

    1. Строим целевой портфель на ``total_budget_rub`` (holdings + cash).
    2. Считаем diff по лотам относительно ``current_lots_by_isin``.
    3. Покупаем в пределах ``cash_to_deploy_rub`` (новые ISIN, затем докупки).
    """
    if cash_to_deploy_rub <= 0:
        return [], ["Сумма к развёртыванию ≤ 0 — нечего распределять."]

    existing_isins = set(current_lots_by_isin)
    existing_count = len(existing_isins)
    new_slots = max(0, MAX_AUTO_POSITIONS - existing_count)
    notes: list[str] = []

    if existing_count >= MAX_AUTO_POSITIONS:
        deploy_universe = _top_scored_existing_bonds(
            universe,
            existing_isins,
            profile=profile,
            horizon_date=horizon_date,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            api_trade_only=api_trade_only,
            duration_policy=duration_policy,
        )
        notes.append("Лимит 10 позиций — докупаем только существующие бумаги.")
    else:
        deploy_universe = universe

    target_positions, _, compose_notes = auto_compose(
        initial_amount=total_budget_rub,
        universe=deploy_universe,
        profile=profile,
        horizon_date=horizon_date,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        api_trade_only=api_trade_only,
        duration_policy=duration_policy,
    )
    notes.extend(compose_notes)
    if not target_positions:
        notes.append("Кэш не распределён: не удалось построить целевую структуру.")
        return [], notes

    target_lots_by_isin = {p.isin: p.lots for p in target_positions}
    target_order = [p.isin for p in target_positions]
    universe_by_isin = {b.isin: b for b in universe}
    current_lots = dict(current_lots_by_isin)
    allocations: list[BuyAllocation] = []
    remaining = cash_to_deploy_rub
    buffer = buy_limit_price_buffer(account_kind)

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
        needed_lots = max(0, target_lots - current_lots.get(isin, 0))
        if needed_lots < 1:
            return
        lots = min(needed_lots, int(remaining // lot_cost))
        if lots < 1:
            return
        cost = lots * lot_cost
        last_price = bond.last_price if bond.last_price is not None else 100.0
        allocations.append(
            BuyAllocation(
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
        current_lots[isin] = current_lots.get(isin, 0) + lots
        remaining -= cost

    new_targets = [
        isin for isin in target_order if isin not in existing_isins
    ][:new_slots]
    existing_targets = [isin for isin in target_order if isin in existing_isins]
    for isin in new_targets:
        _allocate_isin(isin, target_lots_by_isin[isin])
    for isin in existing_targets:
        _allocate_isin(isin, target_lots_by_isin[isin])

    if not allocations:
        notes.append("Кэш не распределён: нет подходящих бумаг или сумма слишком мала.")
        return [], notes

    distributed = cash_to_deploy_rub - remaining
    notes.append(
        f"Распределено {distributed:,.0f} ₽ из {cash_to_deploy_rub:,.0f} ₽ по "
        f"{len(allocations)} бумагам. Остаток: {remaining:,.0f} ₽."
    )
    return allocations, notes
