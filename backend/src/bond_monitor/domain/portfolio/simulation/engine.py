"""Event-sourced portfolio cashflow simulation engine."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.cashflow import CashflowEvent, cashflow_event_description
from bond_monitor.domain.portfolio.coupon_schedule import (
    coupon_dates_in_range,
    coupon_payment_per_event,
)
from bond_monitor.domain.portfolio.auto_compose import auto_compose
from bond_monitor.domain.portfolio.deploy_cash import deploy_cash
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    PositionSourceType,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
)
from bond_monitor.domain.portfolio.plan_models import (
    MAX_REINVEST_DEPTH,
    PUT_OFFER_REMINDER_DAYS,
    REINVESTMENT_GAP_DAYS,
    HeldPositionAtHorizon,
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
from bond_monitor.domain.portfolio.redemption import net_redemption_amount
from bond_monitor.domain.portfolio.policies import DurationPolicy
from bond_monitor.domain.portfolio.reinvestment import clear_slot_override, validate_replacement_bond
from bond_monitor.domain.portfolio.selection import has_usable_price
from bond_monitor.domain.portfolio.simulation.events import (
    ScheduledEvent,
    SimEvent,
    SimEventKind,
    event_priority,
)
from bond_monitor.domain.portfolio.simulation.state import OpenPosition, PortfolioState
from bond_monitor.domain.shared.formatting import format_date
from bond_monitor.domain.shared.money import Rub

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


@dataclass
class SimulationResult:
    events: list[CashflowEvent] = field(default_factory=list)
    all_positions: list[PortfolioPosition] = field(default_factory=list)
    resolved_slots: list[ReinvestmentSlot] = field(default_factory=list)
    held_positions: list[HeldPositionAtHorizon] = field(default_factory=list)
    upcoming_put_offers: list[UpcomingPutOffer] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    initial_cash_rub: float = 0.0


def _generation_for(position: PortfolioPosition) -> int:
    if position.source in _PHANTOM_REINVEST_SOURCES:
        return 1
    return 0


def _reinvest_source_type(is_put: bool) -> PositionSourceType:
    return (
        PositionSourceType.REINVEST_PUT_OFFER
        if is_put
        else PositionSourceType.REINVEST_MATURITY
    )


def _position_is_put_at_end(
    position: PortfolioPosition,
    end_date: date | None,
    today: date,
) -> bool:
    return (
        end_date is not None
        and position.offer_date is not None
        and end_date == position.offer_date
        and not put_offer_submission_closed(position, today)
    )


def _schedule_lifecycle(
    queue: list[ScheduledEvent],
    entry: OpenPosition,
    *,
    horizon: date,
    today: date,
    assume_best_put_outcome: bool,
    sequence: list[int],
) -> None:
    position = entry.position
    if entry.closed:
        return
    position_id = id(position)
    end_date = position_end_date(
        position,
        horizon,
        today=today,
        assume_best_put_outcome=assume_best_put_outcome,
    )
    coupon_end = end_date if end_date and end_date <= horizon else horizon
    coupon_gross = coupon_payment_per_event(position)
    if coupon_gross > 0:
        for coupon_date in coupon_dates_in_range(position, coupon_end):
            sequence[0] += 1
            heapq.heappush(
                queue,
                ScheduledEvent(
                    sort_key=(coupon_date, event_priority(SimEventKind.COUPON), sequence[0]),
                    event=SimEvent(
                        kind=SimEventKind.COUPON,
                        date=coupon_date,
                        position_id=position_id,
                    ),
                ),
            )
    if end_date is None or end_date > horizon:
        return
    is_put = _position_is_put_at_end(position, end_date, today)
    kind = SimEventKind.PUT_OFFER if is_put else SimEventKind.MATURITY
    sequence[0] += 1
    heapq.heappush(
        queue,
        ScheduledEvent(
            sort_key=(end_date, event_priority(kind), sequence[0]),
            event=SimEvent(
                kind=kind,
                date=end_date,
                position_id=position_id,
                source_position_isin=position.isin,
                trigger_reason=(
                    ReinvestmentTriggerReason.PUT_OFFER
                    if is_put
                    else ReinvestmentTriggerReason.MATURITY
                ),
                is_put=is_put,
            ),
        ),
    )


def _schedule_deploy(
    queue: list[ScheduledEvent],
    *,
    deploy_date: date,
    source_position_isin: str,
    trigger_reason: ReinvestmentTriggerReason,
    confirmed_isin: str | None,
    is_put: bool,
    parent_generation: int,
    sequence: list[int],
    scheduled_deploy: set[date],
) -> None:
    if deploy_date in scheduled_deploy:
        return
    scheduled_deploy.add(deploy_date)
    sequence[0] += 1
    heapq.heappush(
        queue,
        ScheduledEvent(
            sort_key=(deploy_date, event_priority(SimEventKind.DEPLOY_CASH), sequence[0]),
            event=SimEvent(
                kind=SimEventKind.DEPLOY_CASH,
                date=deploy_date,
                source_position_isin=source_position_isin,
                trigger_reason=trigger_reason,
                confirmed_isin=confirmed_isin,
                is_put=is_put,
                parent_generation=parent_generation,
            ),
        ),
    )


def _find_entry(state: PortfolioState, position_id: int) -> OpenPosition | None:
    for entry in state.open_positions:
        if id(entry.position) == position_id:
            return entry
    return None


def _append_journal_event(
    result: SimulationResult,
    journal_seq: list[int],
    event: CashflowEvent,
) -> None:
    journal_seq[0] += 1
    event.journal_seq = journal_seq[0]
    result.events.append(event)


def _append_held_position_if_beyond_horizon(
    result: SimulationResult,
    position: PortfolioPosition,
    *,
    universe_by_isin: dict[str, BondRecord],
    end_date: date | None,
    horizon: date,
) -> None:
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
    result.held_positions.append(
        HeldPositionAtHorizon(
            position=position,
            estimated_value_rub=est_value,
            valuation_source=valuation_source,
        )
    )
    _ = end_date


def _maybe_append_put_offer_reminder(
    result: SimulationResult,
    position: PortfolioPosition,
    *,
    universe_by_isin: dict[str, BondRecord],
    today: date,
    horizon: date,
    reminded_isins: set[str],
) -> None:
    if (
        position.offer_date is None
        or not (today <= position.offer_date <= horizon)
        or position.isin in reminded_isins
    ):
        return
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
    if not show_reminder:
        return
    result.upcoming_put_offers.append(
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


def run_simulation(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    *,
    today: date,
    horizon: date,
    key_rate: float,
    tax_rate: float,
    initial_cash: float,
    account_snapshot_money_rub: Rub | None,
    assume_best_put_outcome: bool,
    duration_policy: DurationPolicy,
) -> SimulationResult:
    """Построить cashflow-журнал event-sourced симуляцией до горизонта."""
    universe_by_isin = {bond.isin: bond for bond in universe}
    result = SimulationResult(initial_cash_rub=initial_cash)
    state = PortfolioState(cash=initial_cash)

    saved_slots_by_source: dict[str, ReinvestmentSlot] = {}
    for slot in portfolio.slots:
        if slot.source_position_isin:
            saved_slots_by_source[slot.source_position_isin] = slot

    for pos in open_positions(portfolio.positions):
        live_bond = universe_by_isin.get(pos.isin)
        if live_bond is not None:
            sync_put_offer_from_bond(pos, live_bond)

    queue: list[ScheduledEvent] = []
    sequence = [0]
    journal_seq = [0]
    scheduled_deploy: set[date] = set()
    reminded_isins: set[str] = set()

    is_trading = account_snapshot_money_rub is not None
    seed_positions = list(open_positions(portfolio.positions))

    if not is_trading and not seed_positions:
        composed, remaining, compose_notes = auto_compose(
            initial_amount=initial_cash,
            universe=universe,
            profile=portfolio.risk_profile,
            horizon_date=horizon,
            today=today,
            key_rate=key_rate,
            tax_rate=tax_rate,
            api_trade_only=portfolio.api_trade_only,
            duration_policy=duration_policy,
        )
        result.notes.extend(compose_notes)
        seed_positions = composed
        spent = sum(position.purchase_amount_rub for position in composed)
        state.cash = initial_cash - spent

    for position in seed_positions:
        generation = _generation_for(position)
        entry = state.add_position(position, generation=generation)
        emit_initial_purchase = (
            not is_trading
            and position.source == PositionSourceType.INITIAL
            and position.purchase_date <= today
        )
        if emit_initial_purchase:
            _append_journal_event(
                result,
                journal_seq,
                CashflowEvent(
                    date=position.purchase_date,
                    kind="purchase",
                    amount_rub=-position.purchase_amount_rub,
                    description=cashflow_event_description(
                        "purchase",
                        position.name,
                        bonds_count=position.bonds_count,
                        lots=position.lots,
                    ),
                    related_isin=position.isin,
                    is_projected=position.purchase_date > today,
                    position_id=id(position),
                    lots=position.lots,
                    bonds_count=position.bonds_count,
                ),
            )
            state.cash -= position.purchase_amount_rub

        end_date = position_end_date(
            position,
            horizon,
            today=today,
            assume_best_put_outcome=assume_best_put_outcome,
        )
        if end_date is None or end_date > horizon:
            _append_held_position_if_beyond_horizon(
                result,
                position,
                universe_by_isin=universe_by_isin,
                end_date=end_date,
                horizon=horizon,
            )
        else:
            _schedule_lifecycle(
                queue,
                entry,
                horizon=horizon,
                today=today,
                assume_best_put_outcome=assume_best_put_outcome,
                sequence=sequence,
            )

        _maybe_append_put_offer_reminder(
            result,
            position,
            universe_by_isin=universe_by_isin,
            today=today,
            horizon=horizon,
            reminded_isins=reminded_isins,
        )

    while queue:
        scheduled = heapq.heappop(queue)
        event = scheduled.event
        if event.date > horizon:
            continue

        if event.kind == SimEventKind.COUPON:
            if event.position_id is None or not state.is_open(event.position_id):
                continue
            entry = _find_entry(state, event.position_id)
            assert entry is not None
            position = entry.position
            net_factor = 1.0 - tax_rate
            gross = coupon_payment_per_event(position)
            if gross <= 0:
                continue
            _append_journal_event(
                result,
                journal_seq,
                CashflowEvent(
                    date=event.date,
                    kind="coupon",
                    amount_rub=gross * net_factor,
                    description=cashflow_event_description(
                        "coupon",
                        position.name,
                        bonds_count=position.bonds_count,
                    ),
                    related_isin=position.isin,
                    is_projected=event.date > today,
                    position_id=event.position_id,
                    bonds_count=position.bonds_count,
                ),
            )
            state.cash += gross * net_factor
            continue

        if event.kind in (SimEventKind.MATURITY, SimEventKind.PUT_OFFER):
            if event.position_id is None or not state.is_open(event.position_id):
                continue
            entry = _find_entry(state, event.position_id)
            assert entry is not None
            position = entry.position
            is_put = event.kind == SimEventKind.PUT_OFFER
            kind = "put_offer" if is_put else "maturity"
            price_suffix = (
                f" ({position.offer_price_pct:.0f}% номинала)"
                if is_put and position.offer_price_pct is not None
                else ""
            )
            redemption = net_redemption_amount(position, tax_rate, is_put=is_put)
            _append_journal_event(
                result,
                journal_seq,
                CashflowEvent(
                    date=event.date,
                    kind=kind,
                    amount_rub=redemption,
                    description=cashflow_event_description(
                        kind,
                        position.name,
                        bonds_count=position.bonds_count,
                        price_suffix=price_suffix,
                    ),
                    related_isin=position.isin,
                    is_projected=event.date > today,
                    position_id=event.position_id,
                    bonds_count=position.bonds_count,
                ),
            )
            state.cash += redemption
            state.close_position(event.position_id)

            deploy_date = event.date + timedelta(days=REINVESTMENT_GAP_DAYS)
            if deploy_date > horizon:
                continue
            if entry.generation >= MAX_REINVEST_DEPTH:
                result.notes.append(
                    f"{position.name}: достигнут предел глубины реинвестиций "
                    f"({MAX_REINVEST_DEPTH}); дальнейшие цепочки не моделировались."
                )
                continue

            saved = saved_slots_by_source.get(position.isin)
            if saved is not None:
                slot = ReinvestmentSlot(
                    trigger_date=event.date,
                    trigger_reason=event.trigger_reason or ReinvestmentTriggerReason.MATURITY,
                    expected_cash_rub=0.0,
                    suggested_isin=saved.suggested_isin,
                    suggested_name=saved.suggested_name,
                    confirmed_isin=saved.confirmed_isin,
                    gap_days=REINVESTMENT_GAP_DAYS,
                    source_position_isin=position.isin,
                )
            else:
                slot = ReinvestmentSlot(
                    trigger_date=event.date,
                    trigger_reason=event.trigger_reason or ReinvestmentTriggerReason.MATURITY,
                    expected_cash_rub=0.0,
                    suggested_isin=None,
                    suggested_name=None,
                    confirmed_isin=None,
                    gap_days=REINVESTMENT_GAP_DAYS,
                    source_position_isin=position.isin,
                )
            result.resolved_slots.append(slot)
            _schedule_deploy(
                queue,
                deploy_date=deploy_date,
                source_position_isin=position.isin,
                trigger_reason=slot.trigger_reason,
                confirmed_isin=slot.confirmed_isin,
                is_put=is_put,
                parent_generation=entry.generation,
                sequence=sequence,
                scheduled_deploy=scheduled_deploy,
            )
            continue

        if event.kind == SimEventKind.DEPLOY_CASH:
            cash_at_deploy = state.cash
            if cash_at_deploy <= 0:
                continue
            source = _reinvest_source_type(event.is_put)
            confirmed = event.confirmed_isin
            if confirmed:
                bond = universe_by_isin.get(confirmed)
                if bond is not None:
                    invalid = validate_replacement_bond(
                        bond,
                        slot_purchase_date=event.date,
                        horizon=horizon,
                    )
                    if invalid is not None and event.source_position_isin:
                        clear_slot_override(portfolio, event.source_position_isin)
                        result.notes.append(
                            f"Слот {format_date(event.date)}: override «{confirmed}» "
                            f"отклонён ({invalid})."
                        )
                        confirmed = None

            allocations, remaining, deploy_notes = deploy_cash(
                cash_rub=cash_at_deploy,
                current_lots_by_isin=state.lots_by_isin(),
                universe=universe,
                profile=portfolio.risk_profile,
                horizon_date=horizon,
                as_of_date=event.date,
                key_rate=key_rate,
                tax_rate=tax_rate,
                api_trade_only=portfolio.api_trade_only,
                account_kind=portfolio.account_kind,
                duration_policy=duration_policy,
                confirmed_isin=confirmed,
                reinvest_source=source,
            )
            if deploy_notes:
                detail = deploy_notes[-1]
            else:
                detail = "замена не подобрана"

            if allocations:
                primary = max(allocations, key=lambda item: item.estimated_amount_rub)
                for slot in result.resolved_slots:
                    if (
                        slot.source_position_isin == event.source_position_isin
                        and slot.purchase_date == event.date
                    ):
                        slot.suggested_isin = primary.isin
                        slot.suggested_name = primary.name
            else:
                source_name = event.source_position_isin or "позиция"
                for position in state.all_positions:
                    if position.isin == event.source_position_isin:
                        source_name = position.name
                        break
                result.notes.append(
                    f"{source_name}: на дату {format_date(event.date)} "
                    f"не нашлось подходящей замены — {detail}. "
                    f"Деньги останутся в кэш-балансе."
                )

            if deploy_notes and allocations:
                result.notes.append(
                    f"Реинвест {format_date(event.date)}: {deploy_notes[-1]}"
                )

            for allocation in allocations:
                bond = universe_by_isin.get(allocation.isin)
                if bond is None or not has_usable_price(bond):
                    continue
                if state.cash <= 0.01:
                    break
                phantom = position_from_bond(
                    bond,
                    lots=allocation.lots,
                    purchase_date=event.date,
                    source=source,
                )
                cost = phantom.purchase_amount_rub
                if cost > state.cash + 0.01:
                    lot_price = bond.price_per_lot_rub or cost
                    if lot_price <= 0:
                        continue
                    affordable = int(state.cash // lot_price)
                    if affordable < 1:
                        continue
                    phantom = position_from_bond(
                        bond,
                        lots=affordable,
                        purchase_date=event.date,
                        source=source,
                    )
                    cost = phantom.purchase_amount_rub
                if cost > state.cash + 0.01:
                    continue
                generation = event.parent_generation + 1
                entry = state.add_position(phantom, generation=generation)
                state.cash -= cost
                _append_journal_event(
                    result,
                    journal_seq,
                    CashflowEvent(
                        date=event.date,
                        kind="purchase",
                        amount_rub=-cost,
                        description=cashflow_event_description(
                            "purchase",
                            phantom.name,
                            bonds_count=phantom.bonds_count,
                            lots=phantom.lots,
                        ),
                        related_isin=phantom.isin,
                        is_projected=event.date > today,
                        position_id=id(phantom),
                        lots=phantom.lots,
                        bonds_count=phantom.bonds_count,
                    ),
                )
                end_date = position_end_date(
                    phantom,
                    horizon,
                    today=today,
                    assume_best_put_outcome=assume_best_put_outcome,
                )
                if end_date is None or end_date > horizon:
                    _append_held_position_if_beyond_horizon(
                        result,
                        phantom,
                        universe_by_isin=universe_by_isin,
                        end_date=end_date,
                        horizon=horizon,
                    )
                elif generation <= MAX_REINVEST_DEPTH:
                    _schedule_lifecycle(
                        queue,
                        entry,
                        horizon=horizon,
                        today=today,
                        assume_best_put_outcome=assume_best_put_outcome,
                        sequence=sequence,
                    )

            if remaining > 0 and not allocations:
                result.notes.append(
                    f"{format_date(event.date)}: кэш {cash_at_deploy:,.0f} ₽ не распределён."
                )

    result.all_positions = list(state.all_positions)
    return result
