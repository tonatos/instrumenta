"""
Бизнес-логика модуля «Портфель».

Содержит чистые функции (без побочных эффектов и без зависимости от Streamlit):

* :func:`domain.portfolio.selection.risk_profile_filter` — фильтр универса под профиль.
* :func:`auto_compose` — диверсифицированный автосостав начального портфеля.
* :func:`select_replacement` — подбор бумаги-замены для слота реинвестиции.
* :func:`build_plan` — моделирование cashflow и заполнение слотов
  реинвестиции до горизонта планирования.

Все функции принимают ``today`` параметром (а не зовут ``date.today()``
внутри), чтобы план был детерминирован и легко тестировался.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentSlotStatus,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    DEFAULT_PLANNING_POLICY,
    DEFAULT_PORTFOLIO_ALLOCATION_POLICY,
    BondSelectionContext,
)
from bond_monitor.domain.portfolio.selection import (
    api_tradable_filter,
    bond_eligibility_reason,
    explain_selection_failure,
    has_usable_price,
    portfolio_universe_filter,
    put_offer_buy_blocked,
    risk_profile_filter,
    select_best_bond,
    select_ranked_bonds,
)

__all__ = [
    "api_tradable_filter",
    "auto_compose",
    "portfolio_universe_filter",
    "risk_profile_filter",
    "select_replacement",
]
from bond_monitor.domain.shared.formatting import format_date
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.trading.cash_constraints import initial_buy_gap_lots
from bond_monitor.domain.trading.policies import (
    buy_limit_price_buffer,
    suggested_buy_limit_price_pct,
)

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

# Planning / allocation / selection — see ``domain.portfolio.policies``.
_planning = DEFAULT_PLANNING_POLICY
_alloc = DEFAULT_PORTFOLIO_ALLOCATION_POLICY
_selection = DEFAULT_BOND_SELECTION_POLICY

REINVESTMENT_GAP_DAYS: int = _planning.reinvestment_gap_days
PUT_OFFER_REMINDER_DAYS: int = _planning.put_offer_reminder_days
MAX_REINVEST_DEPTH: int = _planning.max_reinvest_depth
COUPON_CASH_REINVEST_INTERVAL_DAYS: int = _planning.coupon_cash_reinvest_interval_days

MAX_POSITION_SHARE: float = _alloc.max_position_share
TARGET_POSITION_SHARE: float = _alloc.target_position_share
MAX_AUTO_POSITIONS: int = _alloc.max_auto_positions
MIN_AUTO_POSITIONS: int = _alloc.min_auto_positions
MIN_POSITION_AMOUNT_RUB: float = _alloc.min_position_amount_rub
MIN_POSITION_SHARE: float = _alloc.min_position_share

MIN_REPLACEMENT_HORIZON_DAYS: int = _selection.min_replacement_horizon_days
MIN_REINVEST_CLEAN_PRICE_PCT: float = _selection.min_clean_price_pct
SLOT_CANDIDATES_LIMIT: int = 30


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class CashflowEvent:
    """Атомарное событие денежного потока в плане портфеля.

    Знак ``amount_rub``:
        * положительный → приток денег в кэш-баланс (купон, погашение, оферта);
        * отрицательный → отток (покупка бумаги).

    ``is_projected = True`` означает, что событие лежит в будущем и
    основано на текущих рыночных параметрах; история (если в портфеле есть
    позиции, купленные в прошлом) идёт с ``is_projected = False``.
    """

    date: date
    kind: str
    amount_rub: float
    description: str
    related_isin: str | None = None
    is_projected: bool = True
    position_id: int | None = None
    lots: int | None = None
    bonds_count: int | None = None


@dataclass
class UpcomingPutOffer:
    """Запись о ближайшей пут-оферте, по которой требуется решение."""

    position: PortfolioPosition
    days_until: int
    days_until_submission_end: int | None
    submission_start: date | None
    submission_end: date | None
    offer_price_pct: float | None
    can_exercise: bool


@dataclass
class HeldPositionAtHorizon:
    """Описание позиции, которая ещё не погашена на ``horizon_date``."""

    position: PortfolioPosition
    estimated_value_rub: float
    valuation_source: str


@dataclass
class PortfolioValuePoint:
    """Снимок стоимости портфеля на дату внутри горизонта плана."""

    date: date
    cash_rub: float
    positions_value_rub: float
    total_value_rub: float


@dataclass
class PortfolioPlan:
    """Снимок портфеля + рассчитанный timeline до ``horizon_date``.

    План — производная сущность: он перестраивается при каждом обращении к
    UI на основе свежих рыночных данных. На диск сохраняются только сам
    портфель и явные пользовательские override-ы (см. :class:`Portfolio`).

    Итоговые поля разделены на «реализованные деньги» и «удерживаемые
    бумаги»:

    * ``final_cash_balance_rub`` — кэш на горизонте после всех погашений
      и реинвестиций;
    * ``held_positions_value_rub`` — рыночная (или face) стоимость бумаг,
      у которых ``maturity_date > horizon_date``;
    * ``final_portfolio_value_rub`` — сумма этих двух, удобная цифра
      «сколько у меня всего».

    ``total_net_profit_rub`` считается ОТ кэша (только то, что
    «материализовалось»), ``total_net_profit_with_held_rub`` — с учётом
    удерживаемых бумаг по их оценочной стоимости.
    """

    portfolio: Portfolio
    events: list[CashflowEvent] = field(default_factory=list)
    resolved_slots: list[ReinvestmentSlot] = field(default_factory=list)
    upcoming_put_offers: list[UpcomingPutOffer] = field(default_factory=list)
    held_positions: list[HeldPositionAtHorizon] = field(default_factory=list)
    # Все позиции, попавшие в worklist при построении плана: исходные +
    # phantom-позиции от реинвест-цепочек + coupon-cash phantom-ы.
    # Нужно, чтобы агрегаты типа взвешенного YTM считались по ВСЕМУ
    # плану, а не только по тому, что сейчас лежит в `portfolio.positions`.
    all_positions: list[PortfolioPosition] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    total_invested_rub: float = 0.0
    total_coupon_gross_rub: float = 0.0
    total_coupon_net_rub: float = 0.0
    total_tax_rub: float = 0.0
    total_redemption_rub: float = 0.0
    final_cash_balance_rub: float = 0.0
    held_positions_value_rub: float = 0.0
    final_portfolio_value_rub: float = 0.0
    total_net_profit_rub: float = 0.0
    total_net_profit_with_held_rub: float = 0.0
    # База вложенного капитала для расчёта прибыли и доходности (старт + top-up).
    invested_capital_rub: float = 0.0
    # «Чистая YTM» текущих INITIAL-позиций, взвешенная по сумме покупки.
    # Это годовая доходность ТЕКУЩИХ позиций к их собственному
    # погашению, она НЕ описывает ожидаемую доходность всего портфеля
    # за весь горизонт (особенно при реинвестициях).
    weighted_ytm_net_pct: float | None = None
    # Средневзвешенная YTM нетто по ВСЕМ позициям плана (initial +
    # phantom-ы реинвест-цепочек). Эта цифра ближе к «средней годовой
    # доходности, на которую может рассчитывать портфель за весь
    # горизонт». Если она существенно ниже weighted_ytm_net_pct —
    # значит реинвестиции «разбавляют» доходность.
    weighted_ytm_net_full_pct: float | None = None
    # Эффективная ГОДОВАЯ доходность портфеля за весь горизонт: plan-XIRR
    # по датам внешних вложений и итоговой стоимости на горизонте.
    effective_annual_return_pct: float | None = None
    # Срок плана (для пересчёта эффективной доходности и формул в UI).
    horizon_days: int = 0
    # Точки роста стоимости портфеля (кэш + бумаги) от ``today`` до горизонта.
    value_timeline: list[PortfolioValuePoint] = field(default_factory=list)


# ── Selection helpers ────────────────────────────────────────────────────────


def _has_usable_price(bond: BondRecord) -> bool:
    """Backward-compatible alias for :func:`selection.has_usable_price`."""
    return has_usable_price(bond)


def _selection_context(
    *,
    profile: RiskProfile,
    horizon_date: date,
    purchase_date: date,
    api_trade_only: bool,
    budget_rub: float | None = None,
) -> BondSelectionContext:
    return BondSelectionContext(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=purchase_date,
        budget_rub=budget_rub,
        api_trade_only=api_trade_only,
    )


def put_offer_can_exercise(position: PortfolioPosition, as_of_date: date) -> bool:
    """Можно ли **прямо сейчас** подать заявку на предъявление по пут-оферте."""
    if put_offer_submission_closed(position, as_of_date):
        return False
    if position.offer_date is None or position.offer_date <= as_of_date:
        return False
    return not (
        position.offer_submission_start is not None and as_of_date < position.offer_submission_start
    )


def put_offer_submission_closed(position: PortfolioPosition, as_of_date: date) -> bool:
    """Окно подачи заявки по пут-оферте уже закрыто (или оферты нет)."""
    if position.offer_date is None or position.offer_date <= as_of_date:
        return True
    if position.offer_submission_end is None:
        return False
    return as_of_date > position.offer_submission_end


def _sync_put_offer_from_bond(position: PortfolioPosition, bond: BondRecord) -> None:
    """Подтянуть окно пут-оферты из live-универса MOEX в позицию."""
    if bond.offer_date is None or bond.offer_date < position.purchase_date:
        return
    position.offer_date = bond.offer_date
    position.offer_submission_start = bond.offer_submission_start
    position.offer_submission_end = bond.offer_submission_end
    position.offer_price_pct = bond.offer_price_pct


def validate_replacement_bond(
    bond: BondRecord,
    *,
    slot_purchase_date: date,
    horizon: date,
) -> str | None:
    """Проверить, что бумага реально может быть куплена в слот на ``slot_purchase_date``.

    Возвращает None, если всё ок; иначе — короткое описание причины,
    почему бумага непригодна (используется в plan.notes).

    Это критический guard от data-bug-ов, где UI-селект слотов
    показывает бумагу с уже прошедшей датой погашения (см.
    :func:`ui.portfolio._render_single_slot` — там кандидаты беруутся из
    всего профильного универса без фильтра по дате). Если попытаться
    «купить» такую бумагу, планировщик эмитит maturity-событие в
    прошлом → cash приходит ДО списания на покупку → удвоение капитала.
    """
    if bond.maturity_date is None:
        return "у бумаги нет даты погашения"
    if bond.maturity_date <= slot_purchase_date:
        return (
            f"бумага гасится {format_date(bond.maturity_date)}, что НЕ позже "
            f"даты покупки {format_date(slot_purchase_date)}"
        )
    days_remaining = (bond.maturity_date - slot_purchase_date).days
    if days_remaining < MIN_REPLACEMENT_HORIZON_DAYS:
        return (
            f"до погашения {format_date(bond.maturity_date)} осталось "
            f"всего {days_remaining} дн. (< MIN_REPLACEMENT_HORIZON_DAYS = "
            f"{MIN_REPLACEMENT_HORIZON_DAYS})"
        )
    if bond.maturity_date > horizon:
        # Это не блокер: бумага уйдёт за горизонт, превратится в
        # HeldPositionAtHorizon. Но в slot мы её принимать не хотим:
        # реинвест должен иметь чёткую дату возврата в кэш в пределах
        # плана, иначе цепочка обрывается.
        return (
            f"погашение {format_date(bond.maturity_date)} позже горизонта "
            f"{format_date(horizon)} — реинвест прервётся"
        )
    if bond.has_default or bond.has_technical_default:
        return "у бумаги статус дефолта / тех.дефолта"
    blocked = put_offer_buy_blocked(bond, slot_purchase_date)
    if blocked is not None:
        return blocked
    return None


def _slot_candidate_dict(bond: BondRecord) -> dict[str, Any]:
    return {
        "isin": bond.isin,
        "name": bond.name,
        "score": bond.score,
        "ytm_net": bond.ytm_net,
    }


def enrich_reinvestment_slot(
    slot: ReinvestmentSlot,
    *,
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    key_rate: float,
    tax_rate: float,
) -> ReinvestmentSlot:
    """Return a copy of *slot* with plan-response metadata for the UI."""
    universe_by_isin = {b.isin: b for b in universe}
    ctx = _selection_context(
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        purchase_date=slot.purchase_date,
        api_trade_only=portfolio.api_trade_only,
        budget_rub=slot.expected_cash_rub,
    )
    ranked = select_ranked_bonds(
        universe,
        ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )
    candidates = [_slot_candidate_dict(b) for b in ranked.bonds[:SLOT_CANDIDATES_LIMIT]]

    status = ReinvestmentSlotStatus.OK
    failure_reason: str | None = None
    target_isin = slot.effective_isin

    if target_isin is None:
        status = ReinvestmentSlotStatus.NO_CANDIDATE
        failure_reason = explain_selection_failure(universe, ctx)
    else:
        target_bond = universe_by_isin.get(target_isin)
        if target_bond is None or not _has_usable_price(target_bond):
            status = ReinvestmentSlotStatus.INVALID_SELECTION
            failure_reason = (
                f"бумага {target_isin} отсутствует в актуальном универсе "
                f"или нет рыночной цены"
            )
        else:
            invalid_reason = validate_replacement_bond(
                target_bond,
                slot_purchase_date=slot.purchase_date,
                horizon=portfolio.horizon_date,
            )
            if invalid_reason is not None:
                status = ReinvestmentSlotStatus.INVALID_SELECTION
                failure_reason = invalid_reason
            else:
                lot_cost = target_bond.price_per_lot_rub or 0.0
                if lot_cost > 0 and slot.expected_cash_rub < lot_cost:
                    status = ReinvestmentSlotStatus.INSUFFICIENT_CASH
                    failure_reason = (
                        f"ожидаемого кэша ({slot.expected_cash_rub:.0f} ₽) не хватает "
                        f"на 1 лот {target_bond.name} ({lot_cost:.0f} ₽)"
                    )

    return ReinvestmentSlot(
        trigger_date=slot.trigger_date,
        trigger_reason=slot.trigger_reason,
        expected_cash_rub=slot.expected_cash_rub,
        suggested_isin=slot.suggested_isin,
        suggested_name=slot.suggested_name,
        confirmed_isin=slot.confirmed_isin,
        gap_days=slot.gap_days,
        source_position_isin=slot.source_position_isin,
        status=status,
        failure_reason=failure_reason,
        eligible_candidates=candidates,
    )


def validate_slot_replacement(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    *,
    slot: ReinvestmentSlot,
    confirmed_isin: str,
    key_rate: float,
    tax_rate: float,
) -> str | None:
    """Validate manual replacement before persisting override."""
    universe_by_isin = {b.isin: b for b in universe}
    bond = universe_by_isin.get(confirmed_isin)
    if bond is None:
        return f"облигация {confirmed_isin} не найдена в универсе MOEX"

    ctx = _selection_context(
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        purchase_date=slot.purchase_date,
        api_trade_only=portfolio.api_trade_only,
        budget_rub=slot.expected_cash_rub,
    )
    eligibility = bond_eligibility_reason(
        bond,
        ctx,
        DEFAULT_BOND_SELECTION_POLICY,
        check_budget=True,
    )
    if eligibility is not None:
        return eligibility

    invalid_reason = validate_replacement_bond(
        bond,
        slot_purchase_date=slot.purchase_date,
        horizon=portfolio.horizon_date,
    )
    if invalid_reason is not None:
        return invalid_reason

    lot_cost = bond.price_per_lot_rub or 0.0
    if lot_cost > 0 and slot.expected_cash_rub < lot_cost:
        return (
            f"ожидаемого кэша ({slot.expected_cash_rub:.0f} ₽) не хватает "
            f"на 1 лот ({lot_cost:.0f} ₽)"
        )
    return None


def prune_stale_slot_overrides(
    portfolio: Portfolio,
    resolved_slots: Sequence[ReinvestmentSlot],
) -> bool:
    """Drop persisted slot overrides that no longer belong to the current plan.

    ``portfolio.slots`` stores only user overrides (``confirmed_isin``) keyed by
    ``source_position_isin``. When the planning horizon changes, downstream
    phantom sources may disappear from :func:`build_plan` output — those stale
    entries must be removed so forecast reinvestment chains stay in sync with
    the new horizon without touching factual ``portfolio.positions``.
    """
    active_sources = {
        slot.source_position_isin
        for slot in resolved_slots
        if slot.source_position_isin
    }
    before = len(portfolio.slots)
    portfolio.slots = [
        slot for slot in portfolio.slots if slot.source_position_isin in active_sources
    ]
    return len(portfolio.slots) != before


def clear_downstream_slot_overrides(
    portfolio: Portfolio,
    source_position_isin: str,
    resolved_slots: Sequence[ReinvestmentSlot],
) -> bool:
    """Clear manual overrides for slots downstream of *source_position_isin*."""
    ordered = sorted(resolved_slots, key=_slot_sort_key)
    slot_index = next(
        (
            i
            for i, slot in enumerate(ordered)
            if slot.source_position_isin == source_position_isin
        ),
        None,
    )
    if slot_index is None:
        return False

    downstream_sources = {
        slot.source_position_isin
        for slot in ordered[slot_index + 1 :]
        if slot.source_position_isin
    }
    changed = False
    for persisted in portfolio.slots:
        if (
            persisted.source_position_isin in downstream_sources
            and persisted.confirmed_isin is not None
        ):
            persisted.confirmed_isin = None
            changed = True
    return changed


def _clear_slot_override(portfolio: Portfolio, source_position_isin: str | None) -> bool:
    """Сбросить ``confirmed_isin`` для слота с данной source-позицией (in-memory).

    Возвращает ``True``, если portfolio.slots были изменены.
    Persistence — ответственность application layer.
    """
    if not source_position_isin:
        return False

    changed = False
    for slot in portfolio.slots:
        if slot.source_position_isin == source_position_isin and slot.confirmed_isin is not None:
            slot.confirmed_isin = None
            changed = True
    if changed:
        portfolio.slots = [
            s
            for s in portfolio.slots
            if s.confirmed_isin is not None or s.source_position_isin != source_position_isin
        ]
    return changed


def _explain_replacement_failure(
    universe: Sequence[BondRecord],
    *,
    target_date: date,
    profile: RiskProfile,
    amount: float,
    horizon_date: date,
    api_trade_only: bool = False,
) -> str:
    """Сформировать пояснение, почему подбор замены не нашёл бумагу."""
    ctx = _selection_context(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=target_date,
        api_trade_only=api_trade_only,
        budget_rub=amount,
    )
    return explain_selection_failure(universe, ctx)


def select_replacement(
    universe: Sequence[BondRecord],
    *,
    target_date: date,
    profile: RiskProfile,
    amount: float,
    horizon_date: date,
    key_rate: float,
    tax_rate: float,
    api_trade_only: bool = False,
) -> tuple[BondRecord | None, str]:
    """Подобрать бумагу-замену для слота реинвестиции.

    Делегирует отбор и ранжирование в :mod:`domain.portfolio.selection`.
    """
    ctx = _selection_context(
        profile=profile,
        horizon_date=horizon_date,
        purchase_date=target_date,
        api_trade_only=api_trade_only,
        budget_rub=amount,
    )
    return select_best_bond(
        universe,
        ctx,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )


# ── Auto-compose ─────────────────────────────────────────────────────────────


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

    selection_ctx = _selection_context(
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
    )
    scored = selection.bonds
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


def position_from_bond(
    bond: BondRecord,
    *,
    lots: int,
    purchase_date: date,
    source: PositionSourceType = PositionSourceType.INITIAL,
) -> PortfolioPosition:
    """Сконвертировать ``BondRecord`` (live из MOEX) в позицию портфеля.

    Используется и в автосоставе, и в ручном добавлении из UI, и при
    генерации фантомных позиций для слотов реинвестиции — все эти места
    единообразно фиксируют рыночные параметры на момент покупки.

    ``offer_date`` нормализуется: если у бумаги в ``BondRecord`` указана
    дата оферты, которая уже прошла относительно ``purchase_date``
    (типичный случай для фантомных reinvest-позиций, которые покупаются
    через несколько месяцев после исходной даты оферты бумаги), —
    обнуляем её. Прошедшая оферта не применима к свежекупленной позиции
    и не должна попадать ни в `_position_end_date`, ни в напоминания о
    пут-офертах.
    """
    clean_pct = bond.last_price or 0.0
    dirty_per_bond = bond.dirty_price_rub or 0.0
    aci_per_bond = bond.accrued_interest or 0.0
    bonds_count = lots * bond.lot_size
    offer_date = bond.offer_date if bond.offer_date and bond.offer_date >= purchase_date else None
    if offer_date and put_offer_buy_blocked(bond, purchase_date):
        offer_date = None
    return PortfolioPosition(
        isin=bond.isin,
        secid=bond.secid,
        name=bond.name,
        lots=lots,
        lot_size=bond.lot_size,
        purchase_clean_price_pct=clean_pct,
        purchase_dirty_price_rub=dirty_per_bond,
        purchase_aci_rub=aci_per_bond,
        purchase_date=purchase_date,
        purchase_amount_rub=dirty_per_bond * bonds_count,
        coupon_rate=bond.coupon_rate,
        face_value=bond.face_value,
        maturity_date=bond.maturity_date,
        offer_date=offer_date,
        offer_submission_start=bond.offer_submission_start if offer_date else None,
        offer_submission_end=bond.offer_submission_end if offer_date else None,
        offer_price_pct=bond.offer_price_pct if offer_date else None,
        coupon_period_days=bond.coupon_period_days,
        next_coupon_date=bond.next_coupon_date,
        source=source,
        put_offer_decision=PutOfferDecision.PENDING,
    )


# ── Plan builder ─────────────────────────────────────────────────────────────


def _position_end_date(
    position: PortfolioPosition,
    horizon: date,
    *,
    today: date,
    assume_best_put_outcome: bool = False,
) -> date | None:
    """Эффективная дата возврата номинала по позиции.

    В режиме TRADING (по умолчанию): дата оферты учитывается ТОЛЬКО при
    явном решении пользователя ``EXERCISE``. Это соответствует
    реальности — без подачи заявки через чат брокера оферта не
    сработает (см. AGENTS.md «Режим торговли → Пут-оферты»).

    В режиме SIMULATION с ``assume_best_put_outcome=True`` для
    ``PENDING`` оферт выбирается выгоднейший сценарий: если оферта
    выгоднее (offer_price_pct ≥ 100% и есть таксая разница), берём
    `offer_date`; иначе оставляем `maturity_date`. Это даёт пользователю
    «оптимистичную» прогнозную доходность без необходимости щёлкать
    EXERCISE/HOLD по каждой бумаге.
    """
    if (
        position.put_offer_decision == PutOfferDecision.EXERCISE
        and position.offer_date is not None
        and not put_offer_submission_closed(position, today)
    ):
        return position.offer_date

    # SIMULATION: для PENDING рассматриваем лучший исход.
    if (
        assume_best_put_outcome
        and position.put_offer_decision == PutOfferDecision.PENDING
        and position.offer_date is not None
        and position.offer_date > today
        and not put_offer_submission_closed(position, today)
        and position.offer_date <= horizon
    ):
        # Подаём оферту, если цена выкупа ≥ 100%. Если меньше — лучше
        # держать до погашения (там 100%).
        offer_price = position.offer_price_pct if position.offer_price_pct is not None else 100.0
        if offer_price >= 100.0:
            return position.offer_date

    return position.maturity_date


def _coupon_dates_in_range(
    position: PortfolioPosition,
    end_date: date,
) -> list[date]:
    """Даты купонных выплат в диапазоне ``(purchase_date, end_date]``.

    Используем ``next_coupon_date`` как якорь и шагаем по
    ``coupon_period_days``. Это важно: у короткой бумаги, где
    ``purchase_date + coupon_period_days`` лежит ЗА датой погашения,
    реальный следующий (и последний) купон всё равно есть — эмитент
    выплачивает его вместе с номиналом в дату погашения. Якорь по
    ``next_coupon_date`` (берётся из MOEX) корректно ловит этот случай:
    последний купон обычно совпадает с ``maturity_date``.

    Если у позиции нет ``next_coupon_date`` (бумага без расписания) —
    fallback на ``purchase_date + period`` (как было раньше). Это
    консервативная оценка для бумаг без явного графика.
    """
    if not position.coupon_period_days or position.coupon_period_days <= 0:
        return []
    if not position.coupon_rate or position.coupon_rate <= 0:
        return []
    period = timedelta(days=position.coupon_period_days)
    if position.next_coupon_date is not None:
        current = position.next_coupon_date
        # ``next_coupon_date`` мог оказаться раньше даты покупки (если
        # бумага добавлена задним числом) — сдвинем вперёд, чтобы не
        # засчитать прошлые купоны как доход портфеля.
        while current <= position.purchase_date:
            current = current + period
    else:
        current = position.purchase_date + period
    dates: list[date] = []
    while current <= end_date:
        dates.append(current)
        current = current + period
    return dates


def _coupon_payment_per_event(position: PortfolioPosition) -> float:
    """Размер одного купонного платежа по позиции (брутто, ₽)."""
    if not position.coupon_rate or not position.coupon_period_days:
        return 0.0
    per_bond = (
        position.face_value * (position.coupon_rate / 100.0) * (position.coupon_period_days / 365.0)
    )
    return per_bond * position.bonds_count


def _price_gain_total(position: PortfolioPosition) -> float:
    """Положительная разница «номинал − чистая цена покупки» × количество."""
    clean_at_purchase = position.purchase_clean_price_pct / 100.0 * position.face_value
    diff = position.face_value - clean_at_purchase
    return diff * position.bonds_count


def _position_cost_basis(position: PortfolioPosition) -> float:
    """Себестоимость позиции в ₽ (по фактически купленным лотам)."""
    if position.actual_lots is not None and position.actual_lots > 0:
        return position.purchase_dirty_price_rub * position.actual_lots * position.lot_size
    if position.purchase_amount_rub > 0:
        return position.purchase_amount_rub
    return position.purchase_dirty_price_rub * position.lots * position.lot_size


def _invested_capital_baseline(
    portfolio: Portfolio,
    *,
    account_snapshot_money_rub: Rub | None,
) -> float:
    """Единая база вложенного капитала для прибыли и прогнозной доходности."""
    if account_snapshot_money_rub is None:
        return portfolio.initial_amount_rub

    deployed = sum(_position_cost_basis(position) for position in portfolio.positions)
    # Факт на счёте: купленные бумаги + свободный кэш. Это и есть вложенный
    # капитал; метаданные acknowledged_top_ups могут завышаться (отменённые
    # batch, частичное исполнение) или отставать (покупки вне batch).
    return deployed + float(account_snapshot_money_rub)


_MAX_PLAN_XIRR_PCT = 200.0


def _plan_xirr_cagr_fallback(
    *,
    final_portfolio_value_rub: float,
    invested_baseline: float,
    horizon_days: int,
) -> float | None:
    if horizon_days <= 0 or invested_baseline <= 0 or final_portfolio_value_rub <= 0:
        return None
    growth = final_portfolio_value_rub / invested_baseline
    try:
        annual_return = growth ** (365.0 / horizon_days) - 1.0
    except (OverflowError, ValueError):
        return None
    return round(annual_return * 100.0, 2)


def _calculate_plan_expected_xirr(
    plan: PortfolioPlan,
    *,
    today: date,
    invested_baseline: float,
    account_snapshot_money_rub: Rub | None,
    horizon_days: int,
) -> float | None:
    """Plan-XIRR: вложения по датам покупок + терминальная стоимость на горизонте."""
    portfolio = plan.portfolio
    horizon = portfolio.horizon_date

    if horizon_days <= 0 or invested_baseline <= 0 or plan.final_portfolio_value_rub <= 0:
        return None

    cashflow: list[tuple[date, float]] = []

    if account_snapshot_money_rub is not None:
        for position in portfolio.positions:
            if position.source != PositionSourceType.INITIAL:
                continue
            cost = _position_cost_basis(position)
            if cost > 0 and position.purchase_date <= horizon:
                cashflow.append((position.purchase_date, -cost))
    else:
        cashflow.append((today, -invested_baseline))

    # Промежуточные и будущие покупки (реинвест) не включаем: они
    # финансируются из купонов/погашений внутри плана, а итог уже
    # отражён в ``final_portfolio_value_rub``.

    cashflow.append((horizon, plan.final_portfolio_value_rub))

    if len(cashflow) < 2:
        return _plan_xirr_cagr_fallback(
            final_portfolio_value_rub=plan.final_portfolio_value_rub,
            invested_baseline=invested_baseline,
            horizon_days=horizon_days,
        )

    has_positive = any(amount > 0 for _, amount in cashflow)
    has_negative = any(amount < 0 for _, amount in cashflow)
    if not (has_positive and has_negative):
        return _plan_xirr_cagr_fallback(
            final_portfolio_value_rub=plan.final_portfolio_value_rub,
            invested_baseline=invested_baseline,
            horizon_days=horizon_days,
        )

    try:
        from pyxirr import InvalidPaymentsError, xirr
    except ImportError:
        logger.error("pyxirr is not installed — plan XIRR calculation unavailable")
        return _plan_xirr_cagr_fallback(
            final_portfolio_value_rub=plan.final_portfolio_value_rub,
            invested_baseline=invested_baseline,
            horizon_days=horizon_days,
        )

    dates = [flow_date for flow_date, _ in cashflow]
    amounts = [amount for _, amount in cashflow]
    try:
        rate = xirr(dates, amounts)
    except (InvalidPaymentsError, ValueError, OverflowError) as exc:
        logger.warning("plan xirr() failed: %s", exc)
        rate = None

    if rate is None:
        return _plan_xirr_cagr_fallback(
            final_portfolio_value_rub=plan.final_portfolio_value_rub,
            invested_baseline=invested_baseline,
            horizon_days=horizon_days,
        )

    xirr_pct = float(rate) * 100.0
    if abs(xirr_pct) > _MAX_PLAN_XIRR_PCT:
        plan.notes.append(
            f"Прогнозная годовая доходность ({xirr_pct:.1f}%) выходит за разумные "
            f"пределы — метрика скрыта. Проверьте вложенный капитал и горизонт."
        )
        return None

    return round(xirr_pct, 2)


def _plan_initial_cash(
    portfolio: Portfolio,
    account_snapshot_money_rub: Rub | None,
) -> float:
    """Стартовый кэш для cashflow и value_timeline.

    SIMULATION: ``initial_amount_rub`` — полный бюджет до стартовых покупок.
    TRADING: фактический остаток на счёте.
    """
    if account_snapshot_money_rub is not None:
        return float(account_snapshot_money_rub)
    return portfolio.initial_amount_rub


def _format_bonds_count_suffix(bonds_count: int | None) -> str:
    if bonds_count is None or bonds_count <= 0:
        return ""
    return f" ({bonds_count} шт.)"


def _cashflow_event_description(
    kind: str,
    name: str,
    *,
    bonds_count: int | None,
    lots: int | None = None,
    price_suffix: str = "",
) -> str:
    suffix = _format_bonds_count_suffix(bonds_count)
    if kind == "purchase":
        return f"Покупка {lots} лот(а) — {name}{suffix}"
    if kind == "coupon":
        return f"Купон по {name}{suffix}"
    if kind == "put_offer":
        return f"Пут-оферта по {name}{price_suffix}{suffix}"
    return f"Погашение {name}{suffix}"


def _bond_name_from_cashflow_description(description: str) -> str:
    text = description
    if text.endswith(" шт.)"):
        text = text.rsplit(" (", 1)[0]
    if " — " in text:
        return text.split(" — ", 1)[1]
    for prefix in ("Купон по ", "Погашение ", "Пут-оферта по "):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def build_plan(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    *,
    today: date,
    key_rate: float,
    tax_rate: float,
    account_snapshot_money_rub: Rub | None = None,
    assume_best_put_outcome: bool = False,
) -> PortfolioPlan:
    """Построить полный timeline портфеля до ``horizon_date``.

    Принципы расчёта:

    * Купонный доход — линейная аппроксимация по ставке и периоду:
      ``face × rate × period_days / 365`` за каждый купон. К каждому купону
      применяется ``tax_rate`` (НДФЛ).
    * Возврат номинала — в дату ``maturity_date`` (или ``offer_date`` при
      решении ``EXERCISE``). С положительной разницы (купили ниже номинала)
      удерживается НДФЛ.
    * Реинвестиция — слот создаётся для каждой позиции с эффективной датой
      окончания внутри горизонта. ``suggested_isin`` подбирается через
      :func:`select_replacement`. Если у слота уже есть ``confirmed_isin``,
      он используется как is — пользовательский выбор не перезаписывается.
    * Цепочки реинвестиций строятся итеративно (BFS по позициям) до
      :data:`MAX_REINVEST_DEPTH`.
    * Накопленный купонный кэш — между крупными событиями раз в
      :data:`COUPON_CASH_REINVEST_INTERVAL_DAYS` проверяется возможность
      реинвестировать накопленное в новую бумагу.
    """
    horizon = portfolio.horizon_date
    universe_by_isin: dict[str, BondRecord] = {b.isin: b for b in universe}

    plan = PortfolioPlan(portfolio=portfolio)

    # Существующие сохранённые слоты индексируем по ISIN исходной позиции,
    # чтобы пользовательский ``confirmed_isin`` не терялся при пересборке.
    saved_slots_by_source: dict[str, ReinvestmentSlot] = {}
    for slot in portfolio.slots:
        if slot.source_position_isin:
            saved_slots_by_source[slot.source_position_isin] = slot

    worklist: list[tuple[PortfolioPosition, int]] = [(p, 0) for p in portfolio.positions]
    # Подтягиваем окна пут-оферт из live-универса в сохранённые позиции.
    for pos in portfolio.positions:
        live_bond = universe_by_isin.get(pos.isin)
        if live_bond is not None:
            _sync_put_offer_from_bond(pos, live_bond)

    # ISIN-ы, для которых уже добавлено напоминание о пут-оферте: одна
    # бумага не должна порождать несколько одинаковых UI-карточек (а ключ
    # ``st.button`` строится из ``portfolio.id + position.isin`` —
    # дубликаты валят рендер Streamlit).
    reminded_isins: set[str] = set()
    while worklist:
        position, depth = worklist.pop(0)
        plan.all_positions.append(position)
        _emit_position_events(
            position,
            plan,
            today,
            horizon,
            tax_rate,
            universe_by_isin=universe_by_isin,
            assume_best_put_outcome=assume_best_put_outcome,
        )

        # Напоминание о пут-оферте — только для исходных позиций пользователя
        # (PENDING), фантомные позиции с ``REINVEST_*`` source тоже могут
        # иметь оферту, и их тоже хочется подсветить.
        if (
            position.offer_date is not None
            and position.put_offer_decision == PutOfferDecision.PENDING
            and today <= position.offer_date <= horizon
            and position.isin not in reminded_isins
        ):
            live_bond = universe_by_isin.get(position.isin)
            if live_bond is not None:
                _sync_put_offer_from_bond(position, live_bond)
            days_until = (position.offer_date - today).days
            days_until_sub_end: int | None = None
            if position.offer_submission_end is not None:
                days_until_sub_end = (position.offer_submission_end - today).days
            can_exercise = put_offer_can_exercise(position, today)
            submission_closed = put_offer_submission_closed(position, today)
            show_reminder = (
                days_until <= PUT_OFFER_REMINDER_DAYS
                or can_exercise
                or (
                    days_until_sub_end is not None
                    and 0 <= days_until_sub_end <= PUT_OFFER_REMINDER_DAYS
                )
            )
            if show_reminder:
                plan.upcoming_put_offers.append(
                    UpcomingPutOffer(
                        position=position,
                        days_until=days_until,
                        days_until_submission_end=days_until_sub_end,
                        submission_start=position.offer_submission_start,
                        submission_end=position.offer_submission_end,
                        offer_price_pct=position.offer_price_pct,
                        can_exercise=can_exercise and not submission_closed,
                    )
                )
                reminded_isins.add(position.isin)

        if (
            position.put_offer_decision == PutOfferDecision.EXERCISE
            and position.offer_date is not None
            and put_offer_submission_closed(position, today)
        ):
            plan.notes.append(
                f"{position.name}: решение «Предъявить» невозможно — окно подачи "
                f"по пут-оферте "
                f"{format_date(position.offer_submission_end)} "
                f"уже закрыто. Расчёт идёт до погашения "
                f"{format_date(position.maturity_date)}."
            )

        end_date = _position_end_date(
            position,
            horizon,
            today=today,
            assume_best_put_outcome=assume_best_put_outcome,
        )
        if end_date is None or end_date > horizon:
            # Позиция не успевает погаситься в горизонте — фиксируем её как
            # «удерживаемую на горизонте». Стоимость на горизонте оцениваем
            # сначала по live-цене (если бумага есть в актуальном универсе),
            # иначе по номиналу × количество облигаций (бумаги обычно
            # подтягиваются к номиналу к погашению).
            live_bond = universe_by_isin.get(position.isin)
            if (
                live_bond is not None
                and live_bond.dirty_price_rub is not None
                and live_bond.dirty_price_rub > 0
            ):
                est_value = live_bond.dirty_price_rub * position.bonds_count
                valuation_source = "live MOEX (грязная цена × кол-во)"
            else:
                est_value = position.face_value * position.bonds_count
                valuation_source = "номинал × кол-во (нет рыночной цены)"
            plan.held_positions.append(
                HeldPositionAtHorizon(
                    position=position,
                    estimated_value_rub=est_value,
                    valuation_source=valuation_source,
                )
            )
            continue

        slot_purchase_date = end_date + timedelta(days=REINVESTMENT_GAP_DAYS)
        if slot_purchase_date > horizon:
            # Бумага гасится в горизонте, но реинвестировать уже некуда:
            # деньги придут «слишком поздно» и просто останутся в кэше
            # (maturity-событие уже эмитировано _emit_position_events).
            continue

        if depth >= MAX_REINVEST_DEPTH:
            plan.notes.append(
                f"{position.name}: достигнут предел глубины реинвестиций "
                f"({MAX_REINVEST_DEPTH}); дальнейшие цепочки не моделировались."
            )
            continue

        is_put = (
            position.put_offer_decision == PutOfferDecision.EXERCISE
            and position.offer_date is not None
            and not put_offer_submission_closed(position, today)
        )
        net_at_end = (
            _net_redemption_amount(position, tax_rate, is_put=is_put)
            if is_put
            else _net_redemption_amount(position, tax_rate)
        )

        slot = saved_slots_by_source.get(position.isin)
        replacement_failure_reason: str | None = None
        if slot is None:
            suggested, selection_note = select_replacement(
                universe,
                target_date=slot_purchase_date,
                profile=portfolio.risk_profile,
                amount=net_at_end,
                horizon_date=horizon,
                key_rate=key_rate,
                tax_rate=tax_rate,
                api_trade_only=portfolio.api_trade_only,
            )
            if suggested:
                if selection_note:
                    plan.notes.append(
                        f"Слот {format_date(slot_purchase_date)} ({position.name}): {selection_note}."
                    )
            else:
                replacement_failure_reason = selection_note
            slot = ReinvestmentSlot(
                trigger_date=end_date,
                trigger_reason=(
                    ReinvestmentTriggerReason.PUT_OFFER
                    if is_put
                    else ReinvestmentTriggerReason.MATURITY
                ),
                expected_cash_rub=net_at_end,
                suggested_isin=suggested.isin if suggested else None,
                suggested_name=suggested.name if suggested else None,
                gap_days=REINVESTMENT_GAP_DAYS,
                source_position_isin=position.isin,
            )
        else:
            slot.expected_cash_rub = net_at_end
            slot.trigger_date = end_date
            slot.trigger_reason = (
                ReinvestmentTriggerReason.PUT_OFFER
                if is_put
                else ReinvestmentTriggerReason.MATURITY
            )
            slot.gap_days = REINVESTMENT_GAP_DAYS
            if not slot.suggested_isin and not slot.confirmed_isin:
                suggested, selection_note = select_replacement(
                    universe,
                    target_date=slot_purchase_date,
                    profile=portfolio.risk_profile,
                    amount=net_at_end,
                    horizon_date=horizon,
                    key_rate=key_rate,
                    tax_rate=tax_rate,
                    api_trade_only=portfolio.api_trade_only,
                )
                if suggested:
                    slot.suggested_isin = suggested.isin
                    slot.suggested_name = suggested.name
                    if selection_note:
                        plan.notes.append(
                            f"Слот {format_date(slot_purchase_date)} ({position.name}): {selection_note}."
                        )
                else:
                    replacement_failure_reason = selection_note

        plan.resolved_slots.append(slot)

        target_isin = slot.effective_isin
        if not target_isin:
            detail = replacement_failure_reason or "замена не подобрана"
            plan.notes.append(
                f"{position.name}: на дату {format_date(end_date)} "
                f"не нашлось подходящей замены — {detail}. "
                f"Деньги останутся в кэш-балансе."
            )
            continue

        target_bond = universe_by_isin.get(target_isin)
        if target_bond is None or not _has_usable_price(target_bond):
            plan.notes.append(
                f"Слот {format_date(end_date)}: бумага {target_isin} нет в "
                f"актуальном универсе MOEX или нет рыночной цены."
            )
            continue

        invalid_reason = validate_replacement_bond(
            target_bond,
            slot_purchase_date=slot_purchase_date,
            horizon=horizon,
        )
        if invalid_reason is not None:
            # Сбрасываем сохранённый битый confirmed_isin: при следующем
            # rerun планировщик предложит автозамену (или явно скажет, что
            # её нет). Иначе пользовательский override застрянет и будет
            # каждый раз генерировать абсурдный cashflow.
            cleared_confirmed = slot.confirmed_isin
            if cleared_confirmed:
                _clear_slot_override(portfolio, slot.source_position_isin)
                # ``_clear_slot_override`` мутирует тот же
                # объект слота в ``portfolio.slots`` (а это та же ссылка,
                # что в ``saved_slots_by_source`` и в ``plan.resolved_slots``),
                # поэтому отдельно ``slot.confirmed_isin = None``
                # выставлять не нужно.
                plan.notes.append(
                    f"Слот {format_date(end_date)}: ваш override "
                    f"«{cleared_confirmed}» отклонён ({invalid_reason}). "
                    f"Override сброшен. Выберите другую бумагу или "
                    f"оставьте автозамену."
                )
            else:
                plan.notes.append(
                    f"Слот {format_date(end_date)}: подобранная замена "
                    f"{target_bond.name} непригодна ({invalid_reason})."
                )
            continue

        lot_cost = target_bond.price_per_lot_rub or 0.0
        max_lots = int(net_at_end // lot_cost) if lot_cost > 0 else 0
        if max_lots < 1:
            plan.notes.append(
                f"Слот {format_date(end_date)}: ожидаемого кэша "
                f"({net_at_end:.0f} ₽) не хватает на 1 лот {target_bond.name} "
                f"({lot_cost:.0f} ₽)."
            )
            continue

        phantom = position_from_bond(
            target_bond,
            lots=max_lots,
            purchase_date=slot_purchase_date,
            source=(
                PositionSourceType.REINVEST_PUT_OFFER
                if is_put
                else PositionSourceType.REINVEST_MATURITY
            ),
        )
        worklist.append((phantom, depth + 1))

    # Купонный кэш: только в симуляции. В TRADING реинвестиции идут через
    # pending operations и фактический баланс счёта.
    if account_snapshot_money_rub is None:
        _maybe_add_coupon_cash_reinvestments(
            plan,
            universe,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            assume_best_put_outcome=assume_best_put_outcome,
        )

    plan.resolved_slots = _merge_reinvestment_slots(plan.resolved_slots)
    plan.resolved_slots.sort(key=_slot_sort_key)
    plan.resolved_slots = [
        enrich_reinvestment_slot(
            slot,
            portfolio=portfolio,
            universe=universe,
            key_rate=key_rate,
            tax_rate=tax_rate,
        )
        for slot in plan.resolved_slots
    ]

    initial_cash = _plan_initial_cash(portfolio, account_snapshot_money_rub)
    _cap_purchase_events_to_cash(
        plan,
        initial_cash=initial_cash,
        today=today,
    )

    plan.events = _merge_cashflow_events(plan.events)

    _finalize_plan_totals(
        plan,
        universe_by_isin,
        today=today,
        tax_rate=tax_rate,
        account_snapshot_money_rub=account_snapshot_money_rub,
    )
    _build_value_timeline(
        plan,
        today=today,
        assume_best_put_outcome=assume_best_put_outcome,
        account_snapshot_money_rub=account_snapshot_money_rub,
    )
    if prune_stale_slot_overrides(portfolio, plan.resolved_slots):
        portfolio.touch()
    return plan


def _emit_position_events(
    position: PortfolioPosition,
    plan: PortfolioPlan,
    today: date,
    horizon: date,
    tax_rate: float,
    universe_by_isin: dict[str, BondRecord] | None = None,
    *,
    assume_best_put_outcome: bool = False,
) -> None:
    """Сгенерировать cashflow-события для одной позиции (purchase, coupons, redemption).

    Соглашение по покупкам:

    * В SIMULATION стартовые INITIAL-покупки эмитятся как события, а
      running balance начинается с ``initial_amount_rub``.
    * В TRADING полные INITIAL-покупки уже на счёте; эмитится только gap
      (``needs_initial_buy``).
    * Будущие покупки и фантомы реинвестиции всегда попадают в timeline.

    ``universe_by_isin`` нужен для бэкфилла ``next_coupon_date`` у
    позиций, сохранённых до того, как поле было добавлено: если у
    позиции дата неизвестна, но бумага есть в актуальном универсе MOEX,
    мы её подтянем.
    """
    position_id = id(position)
    bonds_count = position.bonds_count
    is_future_purchase = position.purchase_date > today
    is_reinvestment = position.source != PositionSourceType.INITIAL
    emit_initial_purchase = (
        not plan.portfolio.is_trading
        and position.source == PositionSourceType.INITIAL
        and position.purchase_date <= today
    )
    needs_initial_buy = False
    purchase_lots = position.lots
    purchase_amount_rub = position.purchase_amount_rub
    purchase_date = position.purchase_date
    if (
        plan.portfolio.is_trading
        and position.source == PositionSourceType.INITIAL
        and position.actual_lots is not None
    ):
        gap_lots = initial_buy_gap_lots(plan.portfolio, position)
        if gap_lots > 0:
            purchase_lots = gap_lots
            unit_dirty = position.purchase_dirty_price_rub
            if universe_by_isin is not None:
                live_bond = universe_by_isin.get(position.isin)
                if live_bond is not None and live_bond.dirty_price_rub:
                    unit_dirty = live_bond.dirty_price_rub
            purchase_amount_rub = unit_dirty * gap_lots * position.lot_size
            purchase_date = today
            needs_initial_buy = True

    if is_future_purchase or is_reinvestment or needs_initial_buy or emit_initial_purchase:
        plan.events.append(
            CashflowEvent(
                date=purchase_date,
                kind="purchase",
                amount_rub=-purchase_amount_rub,
                description=_cashflow_event_description(
                    "purchase",
                    position.name,
                    bonds_count=purchase_lots * position.lot_size,
                    lots=purchase_lots,
                ),
                related_isin=position.isin,
                is_projected=purchase_date > today,
                position_id=position_id,
                lots=purchase_lots,
                bonds_count=purchase_lots * position.lot_size,
            )
        )

    if position.next_coupon_date is None and universe_by_isin is not None:
        live_bond = universe_by_isin.get(position.isin)
        if live_bond is not None and live_bond.next_coupon_date is not None:
            position.next_coupon_date = live_bond.next_coupon_date

    end_date = _position_end_date(
        position,
        horizon,
        today=today,
        assume_best_put_outcome=assume_best_put_outcome,
    )
    coupon_end = end_date if end_date and end_date <= horizon else horizon

    coupon_gross = _coupon_payment_per_event(position)
    if coupon_gross > 0:
        net_factor = 1.0 - tax_rate
        for d in _coupon_dates_in_range(position, coupon_end):
            plan.events.append(
                CashflowEvent(
                    date=d,
                    kind="coupon",
                    amount_rub=coupon_gross * net_factor,
                    description=_cashflow_event_description(
                        "coupon",
                        position.name,
                        bonds_count=bonds_count,
                    ),
                    related_isin=position.isin,
                    is_projected=d > today,
                    position_id=position_id,
                    bonds_count=bonds_count,
                )
            )

    if end_date is None or end_date > horizon:
        return

    is_put = (
        position.put_offer_decision == PutOfferDecision.EXERCISE
        and position.offer_date is not None
        and not put_offer_submission_closed(position, today)
    )
    if is_put:
        price_suffix = (
            f" ({position.offer_price_pct:.0f}% номинала)"
            if position.offer_price_pct is not None
            else ""
        )
        kind = "put_offer"
    else:
        price_suffix = ""
        kind = "maturity"
    redemption = _net_redemption_amount(position, tax_rate, is_put=is_put)
    plan.events.append(
        CashflowEvent(
            date=end_date,
            kind=kind,
            amount_rub=redemption,
            description=_cashflow_event_description(
                kind,
                position.name,
                bonds_count=bonds_count,
                price_suffix=price_suffix,
            ),
            related_isin=position.isin,
            is_projected=end_date > today,
            position_id=position_id,
            bonds_count=bonds_count,
        )
    )


def _net_redemption_amount(
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


def _cap_purchase_events_to_cash(
    plan: PortfolioPlan,
    *,
    initial_cash: float,
    today: date,
) -> None:
    """Не допускать в cashflow покупок, превышающих доступный кэш.

    В TRADING ``initial_cash`` — снимок баланса счёта; в симуляции —
    ``initial_amount_rub``. Вызывается до merge событий, чтобы
    каждая отложенная покупка однозначно соответствовала фантомной позиции.

    Отложенные покупки полностью убирают связанную фантомную позицию
    (купоны, погашение, оценку в value_timeline).
    """
    running_cash = initial_cash
    kept: list[CashflowEvent] = []
    deferred: list[str] = []
    deferred_position_ids: set[int] = set()

    for event in sorted(plan.events, key=_event_sort_key):
        if event.kind == "purchase" and event.date >= today:
            cost = -event.amount_rub
            if cost > running_cash + 0.01:
                deferred.append(
                    f"{event.description}: нужно {cost:,.0f} ₽, доступно {running_cash:,.0f} ₽"
                )
                if event.position_id is not None:
                    deferred_position_ids.add(event.position_id)
                continue
        running_cash += event.amount_rub
        kept.append(event)

    if deferred:
        plan.notes.append(
            "Часть покупок не включена в прогноз — на счёте недостаточно свободных средств."
        )
        plan.notes.extend(deferred[:3])
        if len(deferred) > 3:
            plan.notes.append(f"…и ещё {len(deferred) - 3} отложенных покупок.")
    plan.events = kept
    _prune_deferred_positions(plan, deferred_position_ids)


def _prune_deferred_positions(plan: PortfolioPlan, deferred_position_ids: set[int]) -> None:
    """Удалить фантомные позиции, чьи покупки не прошли cap по кэшу."""
    if not deferred_position_ids:
        return

    coupon_cash_purchase_dates: set[date] = set()
    for position in plan.all_positions:
        if id(position) not in deferred_position_ids:
            continue
        if position.source == PositionSourceType.REINVEST_COUPON_CASH:
            coupon_cash_purchase_dates.add(position.purchase_date)

    plan.all_positions = [
        position for position in plan.all_positions if id(position) not in deferred_position_ids
    ]
    plan.held_positions = [
        held
        for held in plan.held_positions
        if id(held.position) not in deferred_position_ids
    ]
    plan.events = [
        event for event in plan.events if event.position_id not in deferred_position_ids
    ]
    if coupon_cash_purchase_dates:
        plan.resolved_slots = [
            slot
            for slot in plan.resolved_slots
            if not (
                slot.trigger_reason == ReinvestmentTriggerReason.COUPON_CASH
                and slot.purchase_date in coupon_cash_purchase_dates
            )
        ]


def _maybe_add_coupon_cash_reinvestments(
    plan: PortfolioPlan,
    universe: Sequence[BondRecord],
    *,
    today: date,
    key_rate: float,
    tax_rate: float,
    assume_best_put_outcome: bool = False,
) -> None:
    """Дополнительный проход: реинвестируем накопленный купонный кэш.

    Шагаем по таймлайну, считаем running cash. Каждые
    :data:`COUPON_CASH_REINVEST_INTERVAL_DAYS` проверяем: если cash достаточен
    для покупки лучшего кандидата под профиль, формируем coupon-cash слот и
    разворачиваем по нему фантомную позицию (с купонами и погашением,
    которые тоже добавляются в timeline).

    Цепочку «купонный кэш → купоны нового бонда → ещё один купонный кэш»
    не разворачиваем, чтобы не плодить бесконечные подциклы; пользователь
    увидит остаток в ``final_cash_balance_rub`` и сможет создать слот
    вручную.
    """
    portfolio = plan.portfolio
    horizon = portfolio.horizon_date

    sorted_events = sorted(plan.events, key=_event_sort_key)
    cash = portfolio.initial_amount_rub
    last_check = today

    new_events: list[CashflowEvent] = []
    new_slots: list[ReinvestmentSlot] = []

    for event in sorted_events:
        cash += event.amount_rub
        gap_days = (event.date - last_check).days
        if gap_days < COUPON_CASH_REINVEST_INTERVAL_DAYS:
            continue
        last_check = event.date
        purchase_date = event.date + timedelta(days=REINVESTMENT_GAP_DAYS)
        if purchase_date >= horizon - timedelta(days=MIN_REPLACEMENT_HORIZON_DAYS):
            continue
        if cash <= 0:
            continue

        candidate, fallback_note = select_replacement(
            universe,
            target_date=purchase_date,
            profile=portfolio.risk_profile,
            amount=cash,
            horizon_date=horizon,
            key_rate=key_rate,
            tax_rate=tax_rate,
            api_trade_only=portfolio.api_trade_only,
        )
        if candidate is None:
            continue
        # Defensive: select_replacement уже фильтрует по дате, но если
        # данные универса MOEX «съехали» (стали несвежими), повторно
        # валидируем — это страховка от того, что в coupon-cash попадёт
        # бумага, гасящаяся ДО purchase_date. Лучше пропустить слот, чем
        # сгенерировать абсурдный cashflow.
        if (
            validate_replacement_bond(candidate, slot_purchase_date=purchase_date, horizon=horizon)
            is not None
        ):
            continue
        lot_cost = candidate.price_per_lot_rub or 0.0
        if lot_cost <= 0 or lot_cost > cash:
            continue

        max_lots = int(cash // lot_cost)
        if max_lots < 1:
            continue

        phantom = position_from_bond(
            candidate,
            lots=max_lots,
            purchase_date=purchase_date,
            source=PositionSourceType.REINVEST_COUPON_CASH,
        )
        slot = ReinvestmentSlot(
            trigger_date=event.date,
            trigger_reason=ReinvestmentTriggerReason.COUPON_CASH,
            expected_cash_rub=cash,
            suggested_isin=candidate.isin,
            suggested_name=candidate.name,
            confirmed_isin=None,
            gap_days=REINVESTMENT_GAP_DAYS,
            source_position_isin=None,
        )
        new_slots.append(slot)

        # Эмитим события phantom-позиции напрямую: рекурсивная цепочка
        # купонного-кэша не разворачивается (см. docstring).
        plan.all_positions.append(phantom)
        events_before = len(plan.events)
        _emit_position_events(
            phantom,
            plan,
            today,
            horizon,
            tax_rate,
            assume_best_put_outcome=assume_best_put_outcome,
        )
        new_events.extend(plan.events[events_before:])

        # Если бумага «купонной» реинвестиции не успевает погаситься —
        # фиксируем её как удерживаемую на горизонте.
        phantom_end = _position_end_date(
            phantom,
            horizon,
            today=today,
            assume_best_put_outcome=assume_best_put_outcome,
        )
        if phantom_end is None or phantom_end > horizon:
            est_value = (candidate.dirty_price_rub or candidate.face_value) * phantom.bonds_count
            plan.held_positions.append(
                HeldPositionAtHorizon(
                    position=phantom,
                    estimated_value_rub=est_value,
                    valuation_source="live MOEX (грязная цена × кол-во)",
                )
            )

        invested = phantom.purchase_amount_rub
        if invested > cash + 0.01:
            new_slots.pop()
            plan.all_positions.pop()
            plan.events = plan.events[:events_before]
            plan.held_positions = [
                h for h in plan.held_positions if h.position is not phantom
            ]
            continue
        cash -= invested

    plan.resolved_slots.extend(new_slots)
    if new_slots:
        logger.info("Coupon-cash reinvest slots added: %d", len(new_slots))


def _event_sort_key(event: CashflowEvent) -> tuple[date, int]:
    """Сортировка событий: внутри одной даты сначала покупки, потом купоны/погашения."""
    order = {"purchase": 0, "coupon": 1, "maturity": 2, "put_offer": 2}
    return (event.date, order.get(event.kind, 3))


def _slot_sort_key(slot: ReinvestmentSlot) -> tuple[date, int, str]:
    """Сортировка слотов реинвестиции по дате наступления события."""
    reason_order = {
        ReinvestmentTriggerReason.MATURITY: 0,
        ReinvestmentTriggerReason.PUT_OFFER: 1,
        ReinvestmentTriggerReason.COUPON_CASH: 2,
    }
    return (
        slot.trigger_date,
        reason_order.get(slot.trigger_reason, 3),
        slot.source_position_isin or slot.effective_isin or "",
    )


def _slot_merge_key(slot: ReinvestmentSlot) -> tuple[date, str, str] | tuple[date, str] | None:
    if slot.trigger_reason == ReinvestmentTriggerReason.COUPON_CASH:
        return (slot.trigger_date, slot.trigger_reason.value)
    if slot.source_position_isin:
        return (slot.trigger_date, slot.trigger_reason.value, slot.source_position_isin)
    return None


def _slot_coalesce_key(slot: ReinvestmentSlot) -> tuple[date, str] | None:
    effective_isin = slot.effective_isin
    if not effective_isin:
        return None
    return (slot.purchase_date, effective_isin)


_SLOT_REASON_PRIORITY = {
    ReinvestmentTriggerReason.MATURITY: 0,
    ReinvestmentTriggerReason.PUT_OFFER: 1,
    ReinvestmentTriggerReason.COUPON_CASH: 2,
}


def _copy_reinvestment_slot(slot: ReinvestmentSlot) -> ReinvestmentSlot:
    return ReinvestmentSlot(
        trigger_date=slot.trigger_date,
        trigger_reason=slot.trigger_reason,
        expected_cash_rub=slot.expected_cash_rub,
        suggested_isin=slot.suggested_isin,
        suggested_name=slot.suggested_name,
        confirmed_isin=slot.confirmed_isin,
        gap_days=slot.gap_days,
        source_position_isin=slot.source_position_isin,
    )


def _accumulate_reinvestment_slot(existing: ReinvestmentSlot, slot: ReinvestmentSlot) -> None:
    existing.expected_cash_rub += slot.expected_cash_rub
    if existing.confirmed_isin is None and slot.confirmed_isin is not None:
        existing.confirmed_isin = slot.confirmed_isin
    if existing.suggested_isin is None and slot.suggested_isin is not None:
        existing.suggested_isin = slot.suggested_isin
    if existing.suggested_name is None and slot.suggested_name is not None:
        existing.suggested_name = slot.suggested_name

    existing_priority = _SLOT_REASON_PRIORITY.get(existing.trigger_reason, 99)
    slot_priority = _SLOT_REASON_PRIORITY.get(slot.trigger_reason, 99)
    if slot_priority < existing_priority:
        existing.trigger_reason = slot.trigger_reason
        existing.trigger_date = slot.trigger_date
        if slot.source_position_isin is not None:
            existing.source_position_isin = slot.source_position_isin
    else:
        existing.trigger_date = min(existing.trigger_date, slot.trigger_date)
        if existing.source_position_isin is None and slot.source_position_isin is not None:
            existing.source_position_isin = slot.source_position_isin


def _merge_reinvestment_slot_groups(
    slots: Sequence[ReinvestmentSlot],
    *,
    key_fn: Callable[[ReinvestmentSlot], tuple | None],
) -> list[ReinvestmentSlot]:
    sorted_input = sorted(slots, key=_slot_sort_key)
    merged: dict[tuple, ReinvestmentSlot] = {}
    merge_order: list[tuple] = []
    passthrough: list[ReinvestmentSlot] = []

    for slot in sorted_input:
        key = key_fn(slot)
        if key is None:
            passthrough.append(slot)
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = _copy_reinvestment_slot(slot)
            merge_order.append(key)
            continue
        _accumulate_reinvestment_slot(existing, slot)

    result = [merged[key] for key in merge_order] + passthrough
    result.sort(key=_slot_sort_key)
    return result


def _merge_reinvestment_slots(slots: list[ReinvestmentSlot]) -> list[ReinvestmentSlot]:
    """Объединить дублирующиеся слоты реинвестиции в одну карточку UI.

    Два прохода:

    1. Одинаковые ``trigger_date`` + ``trigger_reason`` + ``source_position_isin``
       (или ``coupon_cash`` на одну дату) — суммируем phantom-позиции одной бумаги.
    2. Одинаковые ``purchase_date`` + ``effective_isin`` — погашение и купонный
       кэш, которые реинвестируются в одну бумагу в один день, показываем одной
       карточкой.
    """
    by_source = _merge_reinvestment_slot_groups(slots, key_fn=_slot_merge_key)
    return _merge_reinvestment_slot_groups(by_source, key_fn=_slot_coalesce_key)


_MERGEABLE_EVENT_KINDS = frozenset({"coupon", "maturity", "put_offer", "purchase"})


def _refresh_merged_cashflow_description(event: CashflowEvent) -> None:
    """Пересобрать описание после слияния событий с суммированным количеством."""
    if not event.related_isin:
        return
    name = _bond_name_from_cashflow_description(event.description)
    if event.kind == "purchase":
        event.description = _cashflow_event_description(
            "purchase",
            name,
            bonds_count=event.bonds_count,
            lots=event.lots,
        )
        return
    price_suffix = ""
    if event.kind == "put_offer" and " (" in event.description:
        tail = event.description.split(" (", 1)[1]
        if "% номинала)" in tail:
            price_suffix = f" ({tail.split(')')[0]})"
    event.description = _cashflow_event_description(
        event.kind,
        name,
        bonds_count=event.bonds_count,
        price_suffix=price_suffix,
    )


def _merge_cashflow_events(events: list[CashflowEvent]) -> list[CashflowEvent]:
    """Объединить события одной бумаги в один день в одну строку cashflow.

    Несколько позиций (initial + phantom-ы реинвестиций) с одним ISIN
    эмитят отдельные купоны/погашения/покупки на одну дату — для UI
    суммируем их в одно событие.
    """
    sorted_input = sorted(events, key=_event_sort_key)
    merged: dict[tuple[date, str, str], CashflowEvent] = {}
    merge_order: list[tuple[date, str, str]] = []
    passthrough: list[CashflowEvent] = []

    for event in sorted_input:
        if event.kind not in _MERGEABLE_EVENT_KINDS or not event.related_isin:
            passthrough.append(event)
            continue
        key = (event.date, event.kind, event.related_isin)
        existing = merged.get(key)
        if existing is None:
            merged[key] = CashflowEvent(
                date=event.date,
                kind=event.kind,
                amount_rub=event.amount_rub,
                description=event.description,
                related_isin=event.related_isin,
                is_projected=event.is_projected,
                lots=event.lots,
                bonds_count=event.bonds_count,
            )
            merge_order.append(key)
            continue
        existing.amount_rub += event.amount_rub
        existing.is_projected = existing.is_projected or event.is_projected
        if event.lots is not None:
            existing.lots = (existing.lots or 0) + event.lots
        if event.bonds_count is not None:
            existing.bonds_count = (existing.bonds_count or 0) + event.bonds_count
        _refresh_merged_cashflow_description(existing)

    result = [merged[key] for key in merge_order] + passthrough
    result.sort(key=_event_sort_key)
    return result


def _weighted_ytm(
    positions: Sequence[PortfolioPosition],
    universe_by_isin: dict[str, BondRecord],
) -> float | None:
    """Средневзвешенная YTM нетто, взвешенная по ``purchase_amount_rub``.

    Возвращает None, если ни одна позиция не нашла актуальную YTM в
    универсе. Используется и для текущих позиций, и для полного набора
    плана (с phantom-ами реинвест-цепочек).
    """
    weight_total = 0.0
    weighted_sum = 0.0
    for position in positions:
        bond = universe_by_isin.get(position.isin)
        if bond is None or bond.ytm_net is None:
            continue
        weight = position.purchase_amount_rub
        weight_total += weight
        weighted_sum += weight * bond.ytm_net
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total


def _finalize_plan_totals(
    plan: PortfolioPlan,
    universe_by_isin: dict[str, BondRecord],
    *,
    today: date,
    tax_rate: float,
    account_snapshot_money_rub: Rub | None = None,
) -> None:
    """Пересчитать агрегаты плана из ``events`` и ``portfolio``.

    ``universe_by_isin`` нужен для расчёта средневзвешенной YTM нетто по
    реально подтверждённым позициям. ``tax_rate`` — для восстановления
    брутто-купонов и налога на курсовую разницу из событий, эмитированных
    в нетто-форме. ``today`` — точка отсчёта для расчёта эффективной
    годовой доходности (горизонт меряется от неё до ``horizon_date``).

    В режиме TRADING (``account_snapshot_money_rub is not None``) стартовая
    точка cash-баланса берётся с брокерского счёта, а не из локального
    ``portfolio.cash_balance_rub`` — это правило «реальность определяющая»
    (см. AGENTS.md «Режим торговли»).
    """
    plan.events.sort(key=_event_sort_key)
    portfolio = plan.portfolio

    # Стартовый кэш: в SIMULATION = `initial_amount_rub` (стартовые покупки
    # эмитятся как события), в TRADING = фактический money_rub со счёта.
    cash = _plan_initial_cash(portfolio, account_snapshot_money_rub)
    if account_snapshot_money_rub is not None:
        initial_spent = 0.0
        for position in portfolio.positions:
            if (
                position.source != PositionSourceType.INITIAL
                or position.purchase_date > portfolio.horizon_date
            ):
                continue
            if position.actual_lots is not None:
                filled_lots = min(position.actual_lots, position.lots)
                initial_spent += position.purchase_dirty_price_rub * filled_lots * position.lot_size
            else:
                initial_spent += position.purchase_amount_rub
    else:
        initial_spent = 0.0
    total_invested = initial_spent
    total_coupon_net = 0.0
    total_redemption = 0.0
    for event in plan.events:
        cash += event.amount_rub
        if event.kind == "purchase":
            total_invested += -event.amount_rub
        elif event.kind == "coupon":
            total_coupon_net += event.amount_rub
        elif event.kind in ("maturity", "put_offer"):
            total_redemption += event.amount_rub

    after_tax_factor = 1.0 - tax_rate
    if after_tax_factor > 0:
        total_coupon_gross = total_coupon_net / after_tax_factor
    else:
        total_coupon_gross = total_coupon_net
    total_coupon_tax = total_coupon_gross - total_coupon_net

    # Налог на курсовую разницу считаем по ВСЕМ позициям плана (в т.ч.
    # phantom-позициям от реинвестиций): они тоже погашаются через
    # _net_redemption_amount, который уже вычитает этот налог из cashflow.
    # Если считать только по portfolio.positions — налог в total_tax_rub
    # будет занижен, хотя на итоговую прибыль это не влияет (деньги уже
    # правильно списаны в событиях).
    price_tax = 0.0
    for position in plan.all_positions:
        gain = _price_gain_total(position)
        if gain > 0:
            price_tax += gain * tax_rate

    held_positions_value = sum(h.estimated_value_rub for h in plan.held_positions)
    final_portfolio_value = cash + held_positions_value

    plan.total_invested_rub = round(total_invested, 2)
    plan.total_coupon_net_rub = round(total_coupon_net, 2)
    plan.total_coupon_gross_rub = round(total_coupon_gross, 2)
    plan.total_tax_rub = round(total_coupon_tax + price_tax, 2)
    plan.total_redemption_rub = round(total_redemption, 2)
    plan.final_cash_balance_rub = round(cash, 2)
    plan.held_positions_value_rub = round(held_positions_value, 2)
    plan.final_portfolio_value_rub = round(final_portfolio_value, 2)
    # Реализованная прибыль = только то, что превратилось в кэш к
    # горизонту, без учёта оценочной стоимости ещё не погашенных бумаг.
    invested_baseline = _invested_capital_baseline(
        portfolio,
        account_snapshot_money_rub=account_snapshot_money_rub,
    )
    plan.invested_capital_rub = round(invested_baseline, 2)
    plan.total_net_profit_rub = round(
        plan.final_cash_balance_rub - invested_baseline,
        2,
    )
    # Прибыль с учётом удерживаемых бумаг — корректнее в случаях, когда
    # часть позиций уходит за горизонт: их оценочная стоимость
    # засчитывается как «недоматериализованная прибыль».
    plan.total_net_profit_with_held_rub = round(
        plan.final_portfolio_value_rub - invested_baseline,
        2,
    )

    # Взвешенный YTM нетто по ТЕКУЩИМ позициям (только то, что сейчас
    # лежит в портфеле, без phantom-ов от реинвест-цепочек). Это
    # «годовая доходность текущих позиций к их собственным погашениям»;
    # она НЕ описывает ожидаемую доходность портфеля за горизонт при
    # наличии реинвестиций (нужно смотреть effective_annual_return_pct).
    weighted_initial = _weighted_ytm(portfolio.positions, universe_by_isin)
    if weighted_initial is not None:
        plan.weighted_ytm_net_pct = round(weighted_initial, 2)

    # YTM по ВСЕМ позициям плана (initial + phantom-ы от реинвест-цепочек):
    # ближе к «средней годовой доходности портфеля за горизонт».
    weighted_full = _weighted_ytm(plan.all_positions, universe_by_isin)
    if weighted_full is not None:
        plan.weighted_ytm_net_full_pct = round(weighted_full, 2)

    # Если реинвестиции «разбавили» доходность относительно initial —
    # явно подсветить это пользователю в notes плана. Порог 0.7 выбран
    # эмпирически: если средняя YTM по реинвестам < 70% от initial —
    # повод задуматься о расширении горизонта или ручном выборе слотов.
    if (
        weighted_initial is not None
        and weighted_initial > 0
        and weighted_full is not None
        and weighted_full < weighted_initial * 0.7
    ):
        dilution_pct = (1.0 - weighted_full / weighted_initial) * 100
        plan.notes.append(
            f"YTM реинвестиций ниже YTM текущих позиций: "
            f"{weighted_full:.1f}% против {weighted_initial:.1f}% "
            f"(разбавление ~{dilution_pct:.0f}%). На дату реинвеста в "
            f"окне до горизонта нет бумаг с такой же высокой YTM. "
            f"Варианты: (1) расширить горизонт портфеля, чтобы появились "
            f"более длинные / доходные бумаги; (2) вручную выбрать "
            f"альтернативу в слотах ниже; (3) принять, что короткие "
            f"бумаги «исчерпали» рыночную премию."
        )

    # Эффективная годовая доходность портфеля за весь горизонт —
    # plan-XIRR по датам вложений и итоговой стоимости; fallback — CAGR
    # на полный вложенный капитал.
    horizon_days = (portfolio.horizon_date - today).days if today else 0
    plan.horizon_days = max(horizon_days, 0)
    plan.effective_annual_return_pct = _calculate_plan_expected_xirr(
        plan,
        today=today,
        invested_baseline=invested_baseline,
        account_snapshot_money_rub=account_snapshot_money_rub,
        horizon_days=plan.horizon_days,
    )


def _position_redemption_gross_value(position: PortfolioPosition, *, is_put: bool) -> float:
    """Рыночная стоимость позиции непосредственно перед погашением/офертой."""
    if is_put:
        price_pct = position.offer_price_pct or 100.0
        redemption_per_bond = position.face_value * (price_pct / 100.0)
    else:
        redemption_per_bond = position.face_value
    return redemption_per_bond * position.bonds_count


def _position_is_put_at_end(position: PortfolioPosition, today: date) -> bool:
    return (
        position.put_offer_decision == PutOfferDecision.EXERCISE
        and position.offer_date is not None
        and not put_offer_submission_closed(position, today)
    )


def _position_market_value_at(
    position: PortfolioPosition,
    as_of: date,
    *,
    horizon: date,
    today: date,
    held_by_position_id: dict[int, HeldPositionAtHorizon],
    assume_best_put_outcome: bool,
) -> float:
    """Оценочная стоимость одной позиции на дату ``as_of`` (линейная к номиналу)."""
    if as_of < position.purchase_date:
        return 0.0

    end_date = _position_end_date(
        position,
        horizon,
        today=today,
        assume_best_put_outcome=assume_best_put_outcome,
    )
    is_put = _position_is_put_at_end(position, today)

    purchase_value = position.purchase_amount_rub
    if end_date is not None and end_date <= as_of and end_date <= horizon:
        return 0.0

    if end_date is None or end_date > horizon:
        held = held_by_position_id.get(id(position))
        terminal_value = (
            held.estimated_value_rub
            if held is not None
            else position.face_value * position.bonds_count
        )
        terminal_date = horizon
    else:
        terminal_value = _position_redemption_gross_value(position, is_put=is_put)
        terminal_date = end_date

    if as_of >= terminal_date:
        if end_date is not None and end_date > horizon:
            return terminal_value
        return 0.0

    span_days = (terminal_date - position.purchase_date).days
    if span_days <= 0:
        return purchase_value
    progress = (as_of - position.purchase_date).days / span_days
    return purchase_value + (terminal_value - purchase_value) * progress


def _build_value_timeline(
    plan: PortfolioPlan,
    *,
    today: date,
    assume_best_put_outcome: bool,
    account_snapshot_money_rub: Rub | None = None,
) -> None:
    """Построить кривую роста стоимости портфеля (кэш + бумаги) до горизонта."""
    portfolio = plan.portfolio
    horizon = portfolio.horizon_date
    if today > horizon:
        plan.value_timeline = []
        return

    if account_snapshot_money_rub is not None:
        initial_cash = float(account_snapshot_money_rub)
    else:
        initial_cash = portfolio.initial_amount_rub

    held_by_position_id = {id(h.position): h for h in plan.held_positions}

    key_dates: set[date] = {today, horizon}
    for event in plan.events:
        if today <= event.date <= horizon:
            key_dates.add(event.date)
    for position in plan.all_positions:
        if today <= position.purchase_date <= horizon:
            key_dates.add(position.purchase_date)
        end_date = _position_end_date(
            position,
            horizon,
            today=today,
            assume_best_put_outcome=assume_best_put_outcome,
        )
        if end_date is not None and today <= end_date <= horizon:
            key_dates.add(end_date)

    sorted_events = sorted(plan.events, key=_event_sort_key)
    timeline: list[PortfolioValuePoint] = []

    for point_date in sorted(key_dates):
        cash = initial_cash
        for event in sorted_events:
            if event.date > point_date:
                break
            cash += event.amount_rub

        positions_value = sum(
            _position_market_value_at(
                position,
                point_date,
                horizon=horizon,
                today=today,
                held_by_position_id=held_by_position_id,
                assume_best_put_outcome=assume_best_put_outcome,
            )
            for position in plan.all_positions
        )
        total = cash + positions_value
        timeline.append(
            PortfolioValuePoint(
                date=point_date,
                cash_rub=round(cash, 2),
                positions_value_rub=round(positions_value, 2),
                total_value_rub=round(total, 2),
            )
        )

    plan.value_timeline = timeline


# ── Top-up distribution ──────────────────────────────────────────────────────


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

    selection_ctx = _selection_context(
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
    for p in portfolio.positions:
        bond = next((b for b in scored if b.isin == p.isin), None)
        unit_cost = bond.price_per_lot_rub if bond and bond.price_per_lot_rub else 0.0
        if unit_cost <= 0:
            unit_cost = (
                p.purchase_dirty_price_rub * p.lot_size if p.purchase_dirty_price_rub else 0.0
            )
        lots_basis = (
            p.actual_lots
            if p.actual_lots is not None and portfolio.is_trading
            else p.lots
        )
        market_value = lots_basis * unit_cost if unit_cost > 0 else p.purchase_amount_rub
        current_value_by_isin[p.isin] = current_value_by_isin.get(p.isin, 0.0) + market_value

    allocations: list[TopUpAllocation] = []
    remaining = top_up_amount_rub
    existing_count = len({p.isin for p in portfolio.positions})

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
