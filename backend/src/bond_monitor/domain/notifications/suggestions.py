"""Map domain alerts to trading suggestions."""

from __future__ import annotations

from bond_monitor.domain.notifications.models import Alert, AlertKind
from bond_monitor.domain.trading.suggestions import Suggestion
from bond_monitor.domain.trading.ids import stable_id


def alerts_to_suggestions(alerts: list[Alert]) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for alert in alerts:
        suggestion = _alert_to_suggestion(alert)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _alert_to_suggestion(alert: Alert) -> Suggestion | None:
    if alert.kind == AlertKind.PUT_OFFER_ACTION:
        return Suggestion(
            id=stable_id(alert.portfolio_id, "put_offer", alert.isin),
            kind="put_offer_reminder",
            isin=alert.isin,
            name=alert.name,
            lots=alert.lots,
            figi=alert.figi,
            suggested_price_pct=alert.suggested_price_pct,
            reason=alert.reason,
            due_date=alert.due_date,
            chat_template=alert.chat_template,
            urgency=alert.urgency,
            offer_window_status=alert.offer_window_status,
            submission_start=alert.submission_start,
            submission_end=alert.submission_end,
        )
    if alert.kind == AlertKind.PUT_OFFER_WATCH:
        return Suggestion(
            id=stable_id(alert.portfolio_id, "put_offer_watch", alert.isin),
            kind="put_offer_watch",
            isin=alert.isin,
            name=alert.name,
            lots=alert.lots,
            figi=alert.figi,
            suggested_price_pct=alert.suggested_price_pct,
            reason=alert.reason,
            due_date=alert.due_date,
            chat_template=None,
            urgency="normal",
            offer_window_status=alert.offer_window_status,
            submission_start=alert.submission_start,
            submission_end=alert.submission_end,
        )
    if alert.kind == AlertKind.RISK_ESCALATION:
        primary_kind = alert.escalation_kinds[0] if alert.escalation_kinds else "risk"
        return Suggestion(
            id=stable_id(alert.portfolio_id, "risk_sell", f"{alert.isin}:{primary_kind}"),
            kind="sell",
            isin=alert.isin,
            name=alert.name,
            lots=alert.lots,
            figi=alert.figi,
            suggested_price_pct=alert.suggested_price_pct,
            market_price_pct=alert.market_price_pct,
            reason=alert.reason,
            urgency=alert.urgency,
            risk_acknowledgeable=alert.risk_acknowledgeable,
        )
    return None
