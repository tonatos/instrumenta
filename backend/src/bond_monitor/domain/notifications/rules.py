"""Extensible portfolio alert rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.bonds.offers import (
    bond_offer_view,
    put_offer_action_message,
    put_offer_awareness_message,
)
from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.domain.notifications.policies import DEFAULT_NOTIFICATION_POLICY, NotificationPolicy
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.portfolio.policies import DEFAULT_RISK_MONITOR_POLICY, RiskMonitorPolicy
from bond_monitor.domain.portfolio.put_offer import put_offer_awareness_due, put_offer_submit_due
from bond_monitor.domain.portfolio.risk_monitor import detect_risk_escalations, risk_snapshot_from_bond
from bond_monitor.domain.trading.holdings import HoldingView
from bond_monitor.domain.trading.policies import (
    reference_market_price_pct,
    sell_limit_price_buffer,
    suggested_sell_limit_price_pct,
)


@dataclass(frozen=True)
class AlertContext:
    portfolio: Portfolio
    holdings: list[HoldingView]
    positions: list[PortfolioPosition]
    universe: Sequence[BondRecord]
    today: date
    notification_policy: NotificationPolicy = DEFAULT_NOTIFICATION_POLICY
    risk_policy: RiskMonitorPolicy = DEFAULT_RISK_MONITOR_POLICY

    @property
    def universe_by_isin(self) -> dict[str, BondRecord]:
        return {bond.isin: bond for bond in self.universe}


class AlertRule(Protocol):
    def evaluate(self, ctx: AlertContext) -> list[Alert]: ...


class PutOfferActionRule:
    def evaluate(self, ctx: AlertContext) -> list[Alert]:
        alerts: list[Alert] = []
        for position in ctx.positions:
            view = bond_offer_view(position, ctx.today)
            if view is None:
                continue
            if not put_offer_submit_due(position, ctx.today):
                continue
            days_until = (
                (view.submission_end - ctx.today).days
                if view.submission_end is not None
                else (view.execution_date - ctx.today).days
            )
            urgency: Literal["normal", "soon", "critical"] = (
                "critical" if days_until <= 7 else "soon"
            )
            detail_key = (
                view.submission_end.isoformat()
                if view.submission_end is not None
                else view.execution_date.isoformat()
            )
            template = (
                f"Здравствуйте! Прошу принять к исполнению заявку на досрочное погашение "
                f"облигаций {position.name} (ISIN {position.isin}) по пут-оферте."
            )
            alerts.append(
                Alert(
                    portfolio_id=ctx.portfolio.id,
                    kind=AlertKind.PUT_OFFER_ACTION,
                    isin=position.isin,
                    name=position.name,
                    lots=position.lots,
                    figi=position.figi,
                    reason=put_offer_action_message(view),
                    urgency=urgency,
                    detail_key=detail_key,
                    due_date=view.submission_end or view.execution_date,
                    chat_template=template,
                    suggested_price_pct=position.offer_price_pct,
                    offer_window_status=view.window_status.value,
                    submission_start=view.submission_start,
                    submission_end=view.submission_end,
                )
            )
        return alerts


class PutOfferWatchRule:
    """Awareness alerts — used by trading advise, not outbound worker by default."""

    def evaluate(self, ctx: AlertContext) -> list[Alert]:
        if not ctx.notification_policy.include_put_offer_watch_in_alerts:
            return []
        alerts: list[Alert] = []
        for position in ctx.positions:
            view = bond_offer_view(position, ctx.today)
            if view is None or not put_offer_awareness_due(position, ctx.today):
                continue
            if put_offer_submit_due(position, ctx.today):
                continue
            alerts.append(
                Alert(
                    portfolio_id=ctx.portfolio.id,
                    kind=AlertKind.PUT_OFFER_WATCH,
                    isin=position.isin,
                    name=position.name,
                    lots=position.lots,
                    figi=position.figi,
                    reason=put_offer_awareness_message(view),
                    urgency="normal",
                    detail_key=view.execution_date.isoformat(),
                    due_date=view.execution_date,
                    offer_window_status=view.window_status.value,
                    submission_start=view.submission_start,
                    submission_end=view.submission_end,
                    suggested_price_pct=position.offer_price_pct,
                )
            )
        return alerts


class RiskEscalationRule:
    def evaluate(self, ctx: AlertContext) -> list[Alert]:
        alerts: list[Alert] = []
        for holding in ctx.holdings:
            if not holding.isin or holding.lots <= 0:
                continue
            baseline = ctx.portfolio.risk_baselines.get(holding.isin)
            if baseline is None:
                continue
            bond = ctx.universe_by_isin.get(holding.isin)
            if bond is None:
                continue
            current = risk_snapshot_from_bond(bond)
            escalations = detect_risk_escalations(
                baseline,
                current,
                policy=ctx.risk_policy,
            )
            if not escalations:
                continue
            urgency: Literal["normal", "soon", "critical"] = (
                "critical" if any(e.urgency == "critical" for e in escalations) else "soon"
            )
            reason = "; ".join(e.reason for e in escalations)
            market_price = reference_market_price_pct(
                bond_last_price=bond.last_price,
                broker_current_price_pct=holding.current_price_pct,
            )
            buffer = sell_limit_price_buffer(ctx.portfolio.account_kind)
            suggested_price = float(suggested_sell_limit_price_pct(market_price, buffer))
            primary = escalations[0]
            alerts.append(
                Alert(
                    portfolio_id=ctx.portfolio.id,
                    kind=AlertKind.RISK_ESCALATION,
                    isin=holding.isin,
                    name=holding.name,
                    lots=holding.lots,
                    figi=holding.figi,
                    reason=f"Ухудшение риск-профиля эмитента: {reason}. Рекомендуем продать.",
                    urgency=urgency,
                    detail_key=primary.kind,
                    suggested_price_pct=suggested_price,
                    market_price_pct=market_price,
                    risk_acknowledgeable=True,
                    escalation_kinds=tuple(e.kind for e in escalations),
                )
            )
        return alerts


DEFAULT_ALERT_RULES: list[AlertRule] = [
    PutOfferActionRule(),
    PutOfferWatchRule(),
    RiskEscalationRule(),
]

WORKER_ALERT_RULES: list[AlertRule] = [
    PutOfferActionRule(),
    RiskEscalationRule(),
]


def collect_alerts(
    portfolio: Portfolio,
    *,
    holdings: list[HoldingView],
    positions: list[PortfolioPosition],
    universe: Sequence[BondRecord],
    today: date,
    rules: Sequence[AlertRule] | None = None,
    notification_policy: NotificationPolicy = DEFAULT_NOTIFICATION_POLICY,
    risk_policy: RiskMonitorPolicy = DEFAULT_RISK_MONITOR_POLICY,
) -> list[Alert]:
    ctx = AlertContext(
        portfolio=portfolio,
        holdings=holdings,
        positions=positions,
        universe=universe,
        today=today,
        notification_policy=notification_policy,
        risk_policy=risk_policy,
    )
    active_rules = list(rules) if rules is not None else list(DEFAULT_ALERT_RULES)
    alerts: list[Alert] = []
    for rule in active_rules:
        alerts.extend(rule.evaluate(ctx))
    return alerts
