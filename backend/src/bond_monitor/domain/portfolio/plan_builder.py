"""Portfolio cashflow plan construction."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.cashflow import (
    CashflowEvent,
    _slot_sort_key,
    cashflow_event_description,
    event_sort_key,
    merge_cashflow_events,
    merge_reinvestment_slots,
)
from bond_monitor.domain.portfolio.coupon_schedule import (
    coupon_dates_in_range,
    coupon_payment_per_event,
)
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
)
from bond_monitor.domain.portfolio.plan_models import (
    COUPON_CASH_REINVEST_INTERVAL_DAYS,
    MAX_REINVEST_DEPTH,
    MIN_REPLACEMENT_HORIZON_DAYS,
    PUT_OFFER_REMINDER_DAYS,
    REINVESTMENT_GAP_DAYS,
    HeldPositionAtHorizon,
    PortfolioPlan,
    PortfolioValuePoint,
    UpcomingPutOffer,
)
from bond_monitor.domain.portfolio.position_factory import (
    position_end_date,
    position_from_bond,
    sync_put_offer_from_bond,
)
from bond_monitor.domain.portfolio.position_status import open_positions
from bond_monitor.domain.portfolio.put_offer import (
    put_offer_can_exercise,
    put_offer_submission_closed,
)
from bond_monitor.domain.portfolio.reinvestment import (
    clear_slot_override,
    enrich_reinvestment_slot,
    prune_stale_slot_overrides,
    select_replacement,
    validate_replacement_bond,
)
from bond_monitor.domain.portfolio.selection import has_usable_price
from bond_monitor.domain.shared.formatting import format_date
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.shared.position_math import position_cost_basis
from bond_monitor.domain.trading.cash_constraints import initial_buy_gap_lots

logger = logging.getLogger(__name__)

_PHANTOM_REINVEST_SOURCES = frozenset(
    {
        PositionSourceType.REINVEST_MATURITY,
        PositionSourceType.REINVEST_PUT_OFFER,
        PositionSourceType.REINVEST_COUPON_CASH,
    }
)

_ON_ACCOUNT_SOURCES = frozenset(
    {
        PositionSourceType.INITIAL,
        PositionSourceType.ADOPTED,
    }
)

_MAX_PLAN_XIRR_PCT = 200.0


def _price_gain_total(position: PortfolioPosition) -> float:
    """Положительная разница «номинал − чистая цена покупки» × количество."""
    clean_at_purchase = position.purchase_clean_price_pct / 100.0 * position.face_value
    diff = position.face_value - clean_at_purchase
    return diff * position.bonds_count


def _invested_capital_baseline(
    portfolio: Portfolio,
    *,
    account_snapshot_money_rub: Rub | None,
) -> float:
    """Единая база вложенного капитала для прибыли и прогнозной доходности."""
    if account_snapshot_money_rub is None:
        return portfolio.initial_amount_rub

    deployed = sum(
        position_cost_basis(position) for position in open_positions(portfolio.positions)
    )
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
        deployed_outflow = 0.0
        for position in open_positions(portfolio.positions):
            if position.source not in _ON_ACCOUNT_SOURCES:
                continue
            if position.is_closed:
                continue
            cost = position_cost_basis(position)
            if cost > 0 and position.purchase_date <= horizon:
                cashflow.append((position.purchase_date, -cost))
                deployed_outflow += cost
        # Свободный кэш на счёте — тоже вложенный капитал; без него XIRR
        # завышается (терминал считается от полной базы, а оттоки — только
        # по купленным бумагам).
        cash_gap = invested_baseline - deployed_outflow
        if cash_gap > 0:
            cashflow.append((today, -cash_gap))
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

    worklist: list[tuple[PortfolioPosition, int]] = [
        (p, 0) for p in open_positions(portfolio.positions)
    ]
    # Подтягиваем окна пут-оферт из live-универса в сохранённые позиции.
    for pos in open_positions(portfolio.positions):
        live_bond = universe_by_isin.get(pos.isin)
        if live_bond is not None:
            sync_put_offer_from_bond(pos, live_bond)

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
                sync_put_offer_from_bond(position, live_bond)
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

        end_date = position_end_date(
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
        if target_bond is None or not has_usable_price(target_bond):
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
                clear_slot_override(portfolio, slot.source_position_isin)
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

    plan.resolved_slots = merge_reinvestment_slots(plan.resolved_slots)
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

    plan.events = merge_cashflow_events(plan.events)

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
    is_reinvestment = position.source in _PHANTOM_REINVEST_SOURCES
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
                description=cashflow_event_description(
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

    end_date = position_end_date(
        position,
        horizon,
        today=today,
        assume_best_put_outcome=assume_best_put_outcome,
    )
    coupon_end = end_date if end_date and end_date <= horizon else horizon

    coupon_gross = coupon_payment_per_event(position)
    if coupon_gross > 0:
        net_factor = 1.0 - tax_rate
        for d in coupon_dates_in_range(position, coupon_end):
            plan.events.append(
                CashflowEvent(
                    date=d,
                    kind="coupon",
                    amount_rub=coupon_gross * net_factor,
                    description=cashflow_event_description(
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
            description=cashflow_event_description(
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

    for event in sorted(plan.events, key=event_sort_key):
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
        held for held in plan.held_positions if id(held.position) not in deferred_position_ids
    ]
    plan.events = [event for event in plan.events if event.position_id not in deferred_position_ids]
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

    sorted_events = sorted(plan.events, key=event_sort_key)
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
        phantom_end = position_end_date(
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
            plan.held_positions = [h for h in plan.held_positions if h.position is not phantom]
            continue
        cash -= invested

    plan.resolved_slots.extend(new_slots)
    if new_slots:
        logger.info("Coupon-cash reinvest slots added: %d", len(new_slots))


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
    plan.events.sort(key=event_sort_key)
    portfolio = plan.portfolio

    # Стартовый кэш: в SIMULATION = `initial_amount_rub` (стартовые покупки
    # эмитятся как события), в TRADING = фактический money_rub со счёта.
    cash = _plan_initial_cash(portfolio, account_snapshot_money_rub)
    if account_snapshot_money_rub is not None:
        initial_spent = 0.0
        for position in open_positions(portfolio.positions):
            if position.is_closed:
                continue
            if (
                position.source not in _ON_ACCOUNT_SOURCES
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
    weighted_initial = _weighted_ytm(open_positions(portfolio.positions), universe_by_isin)
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

    end_date = position_end_date(
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
        end_date = position_end_date(
            position,
            horizon,
            today=today,
            assume_best_put_outcome=assume_best_put_outcome,
        )
        if end_date is not None and today <= end_date <= horizon:
            key_dates.add(end_date)

    sorted_events = sorted(plan.events, key=event_sort_key)
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
