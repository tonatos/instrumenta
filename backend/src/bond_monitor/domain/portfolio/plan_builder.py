"""Portfolio cashflow plan construction (read-model over event-sourced simulation)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.cashflow import (
    journal_sort_key,
    merge_cashflow_events,
    merge_reinvestment_slots,
    running_cash_before_purchase,
)
from bond_monitor.domain.portfolio.duration_metrics import weighted_duration_by_purchase
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition, PositionSourceType
from bond_monitor.domain.portfolio.plan_models import PortfolioPlan, PortfolioValuePoint
from bond_monitor.domain.portfolio.policies import DEFAULT_DURATION_POLICY, DurationPolicy
from bond_monitor.domain.portfolio.position_factory import position_end_date
from bond_monitor.domain.portfolio.position_status import open_positions
from bond_monitor.domain.portfolio.put_offer import put_offer_submission_closed
from bond_monitor.domain.portfolio.redemption import net_redemption_amount, price_gain_total
from bond_monitor.domain.portfolio.reinvestment import (
    enrich_reinvestment_slot,
    prune_stale_slot_overrides,
)
from bond_monitor.domain.portfolio.simulation import run_simulation
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.shared.position_math import position_cost_basis

logger = logging.getLogger(__name__)

_ON_ACCOUNT_SOURCES = frozenset(
    {
        PositionSourceType.INITIAL,
        PositionSourceType.ADOPTED,
    }
)

_MAX_PLAN_XIRR_PCT = 200.0

# Backward compatibility for planner exports and tests.
_net_redemption_amount = net_redemption_amount


def _invested_capital_baseline(
    portfolio: Portfolio,
    *,
    account_snapshot_money_rub: Rub | None,
) -> float:
    if account_snapshot_money_rub is None:
        return portfolio.initial_amount_rub
    deployed = sum(
        position_cost_basis(position) for position in open_positions(portfolio.positions)
    )
    return deployed + float(account_snapshot_money_rub)


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
            cost = position_cost_basis(position)
            if cost > 0 and position.purchase_date <= horizon:
                cashflow.append((position.purchase_date, -cost))
                deployed_outflow += cost
        cash_gap = invested_baseline - deployed_outflow
        if cash_gap > 0:
            cashflow.append((today, -cash_gap))
    else:
        cashflow.append((today, -invested_baseline))

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
            f"Прогнозная XIRR ({xirr_pct:.1f}%) нестабильна при коротком горизонте — "
            f"показана упрощённая CAGR-оценка."
        )
        return _plan_xirr_cagr_fallback(
            final_portfolio_value_rub=plan.final_portfolio_value_rub,
            invested_baseline=invested_baseline,
            horizon_days=horizon_days,
        )

    return round(xirr_pct, 2)


def _plan_initial_cash(
    portfolio: Portfolio,
    account_snapshot_money_rub: Rub | None,
) -> float:
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
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> PortfolioPlan:
    """Построить cashflow-план до ``horizon_date`` через event-sourced симуляцию."""
    horizon = portfolio.horizon_date
    initial_cash = _plan_initial_cash(portfolio, account_snapshot_money_rub)

    simulation = run_simulation(
        portfolio,
        universe,
        today=today,
        horizon=horizon,
        key_rate=key_rate,
        tax_rate=tax_rate,
        initial_cash=initial_cash,
        account_snapshot_money_rub=account_snapshot_money_rub,
        assume_best_put_outcome=assume_best_put_outcome,
        duration_policy=duration_policy,
    )

    plan = PortfolioPlan(portfolio=portfolio)
    plan.initial_cash_rub = simulation.initial_cash_rub
    plan.events = merge_cashflow_events(simulation.events)
    plan.all_positions = simulation.all_positions
    plan.held_positions = simulation.held_positions
    plan.upcoming_put_offers = simulation.upcoming_put_offers
    plan.notes = list(simulation.notes)
    plan.resolved_slots = merge_reinvestment_slots(simulation.resolved_slots)

    for slot in plan.resolved_slots:
        slot.expected_cash_rub = running_cash_before_purchase(
            plan.events,
            slot.purchase_date,
            plan.initial_cash_rub,
        )

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

    universe_by_isin = {bond.isin: bond for bond in universe}
    _finalize_plan_totals(
        plan,
        universe_by_isin,
        today=today,
        tax_rate=tax_rate,
        account_snapshot_money_rub=account_snapshot_money_rub,
        duration_policy=duration_policy,
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


def _weighted_ytm(
    positions: Sequence[PortfolioPosition],
    universe_by_isin: dict[str, BondRecord],
) -> float | None:
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
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
) -> None:
    portfolio = plan.portfolio
    cash = _plan_initial_cash(portfolio, account_snapshot_money_rub)
    if account_snapshot_money_rub is not None:
        initial_spent = sum(
            position.purchase_amount_rub
            for position in open_positions(portfolio.positions)
            if position.source in _ON_ACCOUNT_SOURCES
            and position.purchase_date <= portfolio.horizon_date
        )
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

    price_tax = 0.0
    for position in plan.all_positions:
        gain = price_gain_total(position)
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

    invested_baseline = _invested_capital_baseline(
        portfolio,
        account_snapshot_money_rub=account_snapshot_money_rub,
    )
    plan.invested_capital_rub = round(invested_baseline, 2)
    plan.total_net_profit_rub = round(plan.final_cash_balance_rub - invested_baseline, 2)
    plan.total_net_profit_with_held_rub = round(
        plan.final_portfolio_value_rub - invested_baseline,
        2,
    )

    weighted_initial = _weighted_ytm(open_positions(portfolio.positions), universe_by_isin)
    if weighted_initial is not None:
        plan.weighted_ytm_net_pct = round(weighted_initial, 2)

    weighted_dur = weighted_duration_by_purchase(
        open_positions(portfolio.positions),
        universe_by_isin,
        duration_policy=duration_policy,
    )
    if weighted_dur is not None:
        plan.weighted_duration_years = round(weighted_dur, 2)

    weighted_full = _weighted_ytm(plan.all_positions, universe_by_isin)
    if weighted_full is not None:
        plan.weighted_ytm_net_full_pct = round(weighted_full, 2)

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
            f"(разбавление ~{dilution_pct:.0f}%)."
        )

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
    if is_put:
        price_pct = position.offer_price_pct or 100.0
        redemption_per_bond = position.face_value * (price_pct / 100.0)
    else:
        redemption_per_bond = position.face_value
    return redemption_per_bond * position.bonds_count


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


def _position_market_value_at(
    position: PortfolioPosition,
    as_of: date,
    *,
    horizon: date,
    today: date,
    held_by_position_id: dict[int, object],
    assume_best_put_outcome: bool,
) -> float:
    if as_of < position.purchase_date:
        return 0.0

    end_date = position_end_date(
        position,
        horizon,
        today=today,
        assume_best_put_outcome=assume_best_put_outcome,
    )
    is_put = _position_is_put_at_end(position, end_date, today)
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
    portfolio = plan.portfolio
    horizon = portfolio.horizon_date
    if today > horizon:
        plan.value_timeline = []
        return

    initial_cash = _plan_initial_cash(portfolio, account_snapshot_money_rub)
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

    sorted_events = sorted(plan.events, key=journal_sort_key)
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
        timeline.append(
            PortfolioValuePoint(
                date=point_date,
                cash_rub=round(cash, 2),
                positions_value_rub=round(positions_value, 2),
                total_value_rub=round(cash + positions_value, 2),
            )
        )

    plan.value_timeline = timeline
