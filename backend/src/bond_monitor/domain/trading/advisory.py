"""Stateless trading advisory — recommendations from broker snapshot + market."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.cashflow import CashflowEvent, cashflow_event_description, event_sort_key
from bond_monitor.domain.portfolio.coupon_schedule import coupon_dates_in_range, coupon_payment_per_event
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition, PositionSourceType, RiskProfile
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    DEFAULT_PLANNING_POLICY,
    BondSelectionContext,
    BondSelectionPolicy,
    PlanningPolicy,
)
from bond_monitor.domain.portfolio.position_factory import position_end_date, position_from_bond, sync_put_offer_from_bond
from bond_monitor.domain.portfolio.put_offer import put_offer_submit_due
from bond_monitor.domain.portfolio.selection import select_ranked_bonds
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.ids import stable_id
from bond_monitor.domain.trading.policies import buy_limit_price_buffer, suggested_buy_limit_price_pct
from bond_monitor.domain.trading.ports import BrokerActiveOrder, BrokerOperation, BrokerSnapshot
from bond_monitor.domain.trading.yield_calc import ActualPerformance, summarize_actual_performance

SuggestionKind = Literal["buy", "reinvest", "put_offer_reminder", "sell"]

_MAX_BUY_SUGGESTIONS = 5
_MIN_BUY_CASH_RUB = 5_000.0
_REINVEST_LOOKAHEAD_DAYS = 14


@dataclass(frozen=True)
class AttachPreviewValidation:
    """Мягкая валидация счёта перед attach."""

    can_attach: bool
    blockers: list[str]
    warnings: list[str]
    effective_initial_amount_rub: float


def validate_attach_soft(
    snapshot: BrokerSnapshot,
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
) -> AttachPreviewValidation:
    """Разрешить attach любого счёта; предупреждения вместо блокировок."""
    universe_by_isin = _universe_by_isin(universe)
    holdings = build_holdings(snapshot, universe)
    warnings = collect_account_warnings(snapshot, universe_by_isin, holdings)
    if snapshot.bond_positions:
        warnings.append(
            "На счёте уже есть облигации — рекомендации строятся от фактических позиций."
        )
    effective = max(portfolio.initial_amount_rub, float(snapshot.money_rub))
    return AttachPreviewValidation(
        can_attach=True,
        blockers=[],
        warnings=warnings,
        effective_initial_amount_rub=effective,
    )


@dataclass(frozen=True)
class HoldingView:
    """Позиция на счёте, обогащённая рыночными данными."""

    figi: str
    isin: str
    name: str
    lots: int
    quantity: int
    lot_size: int
    current_price_pct: float | None
    current_nkd_rub: float | None
    ytm: float | None
    maturity_date: date | None
    offer_date: date | None
    market_value_rub: float | None


@dataclass(frozen=True)
class Suggestion:
    """Рекомендация к действию (не persisted pending)."""

    id: str
    kind: SuggestionKind
    isin: str
    name: str
    lots: int
    figi: str | None
    suggested_price_pct: float | None
    reason: str
    due_date: date | None = None
    source_isin: str | None = None
    chat_template: str | None = None
    urgency: Literal["normal", "soon", "critical"] = "normal"


@dataclass
class TradingAdvice:
    """Полный консультативный ответ для UI."""

    holdings: list[HoldingView] = field(default_factory=list)
    cashflow: list[CashflowEvent] = field(default_factory=list)
    performance: ActualPerformance | None = None
    suggestions: list[Suggestion] = field(default_factory=list)
    active_orders: list[BrokerActiveOrder] = field(default_factory=list)
    money_rub: float = 0.0
    available_money_rub: float = 0.0
    blocked_money_rub: float = 0.0
    warnings: list[str] = field(default_factory=list)
    as_of: str = ""


def _universe_by_figi(universe: Sequence[BondRecord]) -> dict[str, BondRecord]:
    result: dict[str, BondRecord] = {}
    for bond in universe:
        if bond.figi:
            result[bond.figi] = bond
    return result


def _universe_by_isin(universe: Sequence[BondRecord]) -> dict[str, BondRecord]:
    return {bond.isin: bond for bond in universe}


def _holding_market_value(
    broker_pos_lots: int,
    lot_size: int,
    current_price_pct: PriceUnitPct | None,
    current_nkd_rub: Rub | None,
    face_value: float,
) -> float | None:
    if current_price_pct is None:
        return None
    clean_per_bond = float(current_price_pct) / 100.0 * face_value
    nkd = float(current_nkd_rub or 0.0)
    quantity = broker_pos_lots * lot_size
    return (clean_per_bond + nkd) * quantity


def build_holdings(
    snapshot: BrokerSnapshot,
    universe: Sequence[BondRecord],
) -> list[HoldingView]:
    """Собрать holdings-view из позиций брокера и рыночного универса."""
    by_figi = _universe_by_figi(universe)
    holdings: list[HoldingView] = []
    for figi, pos in snapshot.bond_positions.items():
        if pos.lots <= 0:
            continue
        bond = by_figi.get(figi)
        name = bond.name if bond else pos.ticker
        isin = bond.isin if bond else ""
        lot_size = bond.lot_size if bond else max(pos.quantity // max(pos.lots, 1), 1)
        current_pct = float(pos.current_price_pct) if pos.current_price_pct is not None else None
        nkd = float(pos.current_nkd_rub) if pos.current_nkd_rub is not None else None
        face = bond.face_value if bond else 1000.0
        market_value = _holding_market_value(pos.lots, lot_size, pos.current_price_pct, pos.current_nkd_rub, face)
        holdings.append(
            HoldingView(
                figi=figi,
                isin=isin,
                name=name,
                lots=pos.lots,
                quantity=pos.quantity,
                lot_size=lot_size,
                current_price_pct=current_pct,
                current_nkd_rub=nkd,
                ytm=bond.ytm if bond else None,
                maturity_date=bond.maturity_date if bond else None,
                offer_date=bond.offer_date if bond else None,
                market_value_rub=market_value,
            )
        )
    holdings.sort(key=lambda h: h.name)
    return holdings


def holdings_to_positions(
    holdings: list[HoldingView],
    universe_by_isin: dict[str, BondRecord],
    *,
    purchase_date: date,
) -> list[PortfolioPosition]:
    """Эфемерные позиции для cashflow/yield из holdings."""
    positions: list[PortfolioPosition] = []
    for holding in holdings:
        bond = universe_by_isin.get(holding.isin)
        if bond is None:
            continue
        position = position_from_bond(
            bond,
            lots=holding.lots,
            purchase_date=purchase_date,
            source=PositionSourceType.ADOPTED,
        )
        position.figi = holding.figi
        sync_put_offer_from_bond(position, bond)
        positions.append(position)
    return positions


def build_holdings_cashflow(
    positions: list[PortfolioPosition],
    *,
    horizon_date: date,
    today: date,
) -> list[CashflowEvent]:
    """Прогнозный cashflow по держимым позициям."""
    events: list[CashflowEvent] = []
    for position in positions:
        end = position_end_date(position, horizon_date, today=today)
        if end is None:
            continue
        for coupon_date in coupon_dates_in_range(position, end):
            if coupon_date <= today:
                continue
            amount = coupon_payment_per_event(position)
            if amount <= 0:
                continue
            events.append(
                CashflowEvent(
                    date=coupon_date,
                    kind="coupon",
                    amount_rub=amount,
                    description=cashflow_event_description(
                        "coupon",
                        position.name,
                        bonds_count=position.bonds_count,
                    ),
                    related_isin=position.isin,
                    is_projected=True,
                    lots=position.lots,
                    bonds_count=position.bonds_count,
                )
            )
        if end > today:
            kind = "put_offer" if position.offer_date == end else "maturity"
            redemption = position.face_value * position.bonds_count
            events.append(
                CashflowEvent(
                    date=end,
                    kind=kind,
                    amount_rub=redemption,
                    description=cashflow_event_description(
                        kind,
                        position.name,
                        bonds_count=position.bonds_count,
                    ),
                    related_isin=position.isin,
                    is_projected=True,
                    lots=position.lots,
                    bonds_count=position.bonds_count,
                )
            )
    events.sort(key=event_sort_key)
    return events


def _buy_suggestions(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    *,
    available_cash: float,
    today: date,
    key_rate: float,
    tax_rate: float,
    policy: BondSelectionPolicy,
) -> list[Suggestion]:
    if available_cash < _MIN_BUY_CASH_RUB:
        return []
    ctx = BondSelectionContext(
        profile=portfolio.risk_profile,
        horizon_date=portfolio.horizon_date,
        purchase_date=today,
        budget_rub=available_cash,
        api_trade_only=portfolio.api_trade_only,
    )
    selection = select_ranked_bonds(
        universe,
        ctx,
        policy,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )
    suggestions: list[Suggestion] = []
    for bond in selection.bonds[:_MAX_BUY_SUGGESTIONS]:
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost <= 0 or lot_cost > available_cash:
            continue
        lots = max(1, int(available_cash // lot_cost))
        if lots <= 0:
            continue
        price_pct = float(
            suggested_buy_limit_price_pct(
                bond.last_price or 100.0,
                buy_limit_price_buffer(portfolio.account_kind),
            )
        )
        reason = "Свободный кэш на счёте — рекомендуем докупить"
        if selection.fallback_note:
            reason = f"{reason}. {selection.fallback_note}"
        suggestions.append(
            Suggestion(
                id=stable_id(portfolio.id, "buy", bond.isin),
                kind="buy",
                isin=bond.isin,
                name=bond.name,
                lots=lots,
                figi=bond.figi,
                suggested_price_pct=price_pct,
                reason=reason,
            )
        )
        break  # одна рекомендация на весь свободный кэш
    return suggestions


def _reinvest_suggestions(
    portfolio: Portfolio,
    positions: list[PortfolioPosition],
    universe: Sequence[BondRecord],
    *,
    today: date,
    key_rate: float,
    tax_rate: float,
    policy: BondSelectionPolicy,
    planning: PlanningPolicy,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    horizon = portfolio.horizon_date
    for position in positions:
        end = position_end_date(position, horizon, today=today)
        if end is None:
            continue
        days_until = (end - today).days
        if days_until < 0 or days_until > _REINVEST_LOOKAHEAD_DAYS:
            continue
        expected_cash = position.face_value * position.bonds_count
        reinvest_date = end + timedelta(days=planning.reinvestment_gap_days)
        if reinvest_date > horizon:
            continue
        ctx = BondSelectionContext(
            profile=portfolio.risk_profile,
            horizon_date=horizon,
            purchase_date=reinvest_date,
            budget_rub=expected_cash,
            api_trade_only=portfolio.api_trade_only,
        )
        selection = select_ranked_bonds(
            universe,
            ctx,
            policy,
            key_rate=key_rate,
            tax_rate=tax_rate,
        )
        if not selection.bonds:
            continue
        replacement = selection.bonds[0]
        price_pct = float(
            suggested_buy_limit_price_pct(
                replacement.last_price or 100.0,
                buy_limit_price_buffer(portfolio.account_kind),
            )
        )
        urgency: Literal["normal", "soon", "critical"] = "soon" if days_until <= 7 else "normal"
        suggestions.append(
            Suggestion(
                id=stable_id(portfolio.id, "reinvest", f"{position.isin}:{end.isoformat()}"),
                kind="reinvest",
                isin=replacement.isin,
                name=replacement.name,
                lots=1,
                figi=replacement.figi,
                suggested_price_pct=price_pct,
                reason=(
                    f"Погашение {position.name} {end.strftime('%d.%m.%Y')} "
                    f"(≈{expected_cash:,.0f} ₽) — рекомендуем реинвестировать"
                ),
                due_date=end,
                source_isin=position.isin,
                urgency=urgency,
            )
        )
    return suggestions


def _put_offer_reminder_suggestions(
    portfolio: Portfolio,
    positions: list[PortfolioPosition],
    *,
    today: date,
) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for position in positions:
        if not put_offer_submit_due(position, today):
            continue
        days_until = (position.offer_date - today).days if position.offer_date else 0
        urgency: Literal["normal", "soon", "critical"] = "critical" if days_until <= 7 else "soon"
        template = (
            f"Здравствуйте! Прошу принять к исполнению заявку на досрочное погашение "
            f"облигаций {position.name} (ISIN {position.isin}) по пут-оферте."
        )
        suggestions.append(
            Suggestion(
                id=stable_id(portfolio.id, "put_offer", position.isin),
                kind="put_offer_reminder",
                isin=position.isin,
                name=position.name,
                lots=position.lots,
                figi=position.figi,
                suggested_price_pct=position.offer_price_pct,
                reason=f"Скоро пут-оферта {position.offer_date.strftime('%d.%m.%Y') if position.offer_date else '—'}",
                due_date=position.offer_date,
                chat_template=template,
                urgency=urgency,
            )
        )
    return suggestions


def collect_account_warnings(
    snapshot: BrokerSnapshot,
    universe_by_isin: dict[str, BondRecord],
    holdings: list[HoldingView],
) -> list[str]:
    """Мягкие предупреждения при привязке / просмотре счёта."""
    warnings: list[str] = []
    if snapshot.has_foreign_instruments:
        warnings.append("На счёте есть инструменты, не относящиеся к облигациям RUB.")
    known_figis = {bond.figi for bond in universe_by_isin.values() if bond.figi}
    for holding in holdings:
        if holding.figi and holding.figi not in known_figis and not holding.isin:
            warnings.append(f"Позиция {holding.name} ({holding.figi}) не найдена в рыночном универсе.")
    return warnings


def advise(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    active_orders: list[BrokerActiveOrder],
    operations: list[BrokerOperation],
    universe: Sequence[BondRecord],
    *,
    key_rate: float,
    tax_rate: float,
    today: date | None = None,
    selection_policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
    planning_policy: PlanningPolicy = DEFAULT_PLANNING_POLICY,
) -> TradingAdvice:
    """Собрать консультативный ответ из брокерского state и рынка."""
    as_of_dt = datetime.now(UTC)
    today = today or as_of_dt.date()
    universe_by_isin = _universe_by_isin(universe)

    holdings = build_holdings(snapshot, universe)
    positions = holdings_to_positions(holdings, universe_by_isin, purchase_date=today)
    cashflow = build_holdings_cashflow(
        positions,
        horizon_date=portfolio.horizon_date,
        today=today,
    )

    perf_portfolio = Portfolio(
        id=portfolio.id,
        name=portfolio.name,
        initial_amount_rub=portfolio.initial_amount_rub,
        horizon_date=portfolio.horizon_date,
        risk_profile=portfolio.risk_profile,
        mode=portfolio.mode,
        account_id=portfolio.account_id,
        account_kind=portfolio.account_kind,
        trading_started_at=portfolio.trading_started_at,
        positions=positions,
    )
    performance = summarize_actual_performance(
        perf_portfolio,
        snapshot,
        operations,
        as_of=as_of_dt,
    )

    available = float(snapshot.available_money_rub)
    buy_suggestions = _buy_suggestions(
        portfolio,
        universe,
        available_cash=available,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        policy=selection_policy,
    )
    reinvest_suggestions = _reinvest_suggestions(
        portfolio,
        positions,
        universe,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        policy=selection_policy,
        planning=planning_policy,
    )
    put_offer_suggestions = _put_offer_reminder_suggestions(portfolio, positions, today=today)
    suggestions = buy_suggestions + reinvest_suggestions + put_offer_suggestions
    warnings = collect_account_warnings(snapshot, universe_by_isin, holdings)

    return TradingAdvice(
        holdings=holdings,
        cashflow=cashflow,
        performance=performance,
        suggestions=suggestions,
        active_orders=list(active_orders),
        money_rub=float(snapshot.money_rub),
        available_money_rub=available,
        blocked_money_rub=float(snapshot.blocked_money_rub),
        warnings=warnings,
        as_of=as_of_dt.isoformat(timespec="seconds"),
    )


__all__ = [
    "AttachPreviewValidation",
    "HoldingView",
    "Suggestion",
    "SuggestionKind",
    "TradingAdvice",
    "advise",
    "build_holdings",
    "build_holdings_cashflow",
    "collect_account_warnings",
    "holdings_to_positions",
    "validate_attach_soft",
]
