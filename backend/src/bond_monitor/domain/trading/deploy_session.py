"""Ephemeral deploy session — frozen buy/reinvest plan for atomic execution."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    DEFAULT_DURATION_POLICY,
    DEFAULT_PLANNING_POLICY,
    BondSelectionPolicy,
    DurationPolicy,
    PlanningPolicy,
)
from bond_monitor.domain.portfolio.selection import has_usable_price
from bond_monitor.domain.trading.holdings import HoldingView
from bond_monitor.domain.trading.ids import stable_id
from bond_monitor.domain.trading.policies import (
    DeploySessionPolicy,
    buy_limit_price_buffer,
    suggested_buy_limit_price_pct,
)
from bond_monitor.domain.trading.ports import BrokerActiveOrder
from bond_monitor.domain.trading.suggestions import Suggestion

def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


DeploySessionStatus = Literal["active", "completed", "cancelled", "expired"]
DeploySessionItemKind = Literal["buy", "reinvest"]

_TERMINAL_ORDER_STATUSES = frozenset(
    {
        "EXECUTION_REPORT_STATUS_FILL",
        "EXECUTION_REPORT_STATUS_CANCELLED",
        "EXECUTION_REPORT_STATUS_REJECTED",
    }
)
_FILLED_ORDER_STATUS = "EXECUTION_REPORT_STATUS_FILL"


@dataclass
class DeploySessionItem:
    id: str
    kind: DeploySessionItemKind
    isin: str
    name: str
    lots: int
    figi: str | None
    suggested_price_pct: float
    estimated_amount_rub: float
    reason: str
    status: DeploySessionItemStatus = "pending"
    source_isin: str | None = None
    due_date: date | None = None
    order_id: str | None = None
    urgency: Literal["normal", "soon", "critical"] = "normal"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "isin": self.isin,
            "name": self.name,
            "lots": self.lots,
            "figi": self.figi,
            "suggested_price_pct": self.suggested_price_pct,
            "estimated_amount_rub": self.estimated_amount_rub,
            "reason": self.reason,
            "status": self.status,
            "source_isin": self.source_isin,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "order_id": self.order_id,
            "urgency": self.urgency,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DeploySessionItem:
        due_raw = data.get("due_date")
        return cls(
            id=str(data["id"]),
            kind=data["kind"],  # type: ignore[arg-type]
            isin=str(data["isin"]),
            name=str(data["name"]),
            lots=int(data["lots"]),
            figi=data.get("figi"),
            suggested_price_pct=float(data["suggested_price_pct"]),
            estimated_amount_rub=float(data["estimated_amount_rub"]),
            reason=str(data["reason"]),
            status=data.get("status", "pending"),  # type: ignore[arg-type]
            source_isin=data.get("source_isin"),
            due_date=date.fromisoformat(due_raw) if due_raw else None,
            order_id=data.get("order_id"),
            urgency=data.get("urgency", "normal"),  # type: ignore[arg-type]
        )


@dataclass
class DeploySession:
    id: str
    portfolio_id: str
    status: DeploySessionStatus
    items: list[DeploySessionItem]
    cash_snapshot_rub: float
    created_at: datetime
    expires_at: datetime
    warnings: list[str] = field(default_factory=list)
    completed_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "portfolio_id": self.portfolio_id,
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "cash_snapshot_rub": self.cash_snapshot_rub,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "warnings": list(self.warnings),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DeploySession:
        completed_raw = data.get("completed_at")
        return cls(
            id=str(data["id"]),
            portfolio_id=str(data["portfolio_id"]),
            status=data["status"],  # type: ignore[arg-type]
            items=[DeploySessionItem.from_dict(item) for item in data.get("items", [])],
            cash_snapshot_rub=float(data["cash_snapshot_rub"]),
            created_at=_as_utc(datetime.fromisoformat(str(data["created_at"]))),
            expires_at=_as_utc(datetime.fromisoformat(str(data["expires_at"]))),
            warnings=list(data.get("warnings") or []),
            completed_at=(
                _as_utc(datetime.fromisoformat(completed_raw)) if completed_raw else None
            ),
        )


@dataclass(frozen=True)
class DeploySessionProgress:
    total: int
    pending: int
    placed: int
    filled: int
    skipped: int
    stale: int


def deploy_session_progress(session: DeploySession) -> DeploySessionProgress:
    counts = {status: 0 for status in ("pending", "placed", "filled", "skipped", "stale")}
    for item in session.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return DeploySessionProgress(
        total=len(session.items),
        pending=counts["pending"],
        placed=counts["placed"],
        filled=counts["filled"],
        skipped=counts["skipped"],
        stale=counts["stale"],
    )


def _item_key(suggestion: Suggestion) -> str:
    if suggestion.kind == "reinvest" and suggestion.source_isin and suggestion.due_date:
        return f"{suggestion.source_isin}:{suggestion.due_date.isoformat()}"
    return suggestion.isin


def _estimated_amount_rub(
    suggestion: Suggestion,
    universe_by_isin: dict[str, BondRecord],
) -> float:
    bond = universe_by_isin.get(suggestion.isin)
    if bond is not None and bond.price_per_lot_rub:
        return round(suggestion.lots * bond.price_per_lot_rub, 2)
    if bond is not None:
        face = bond.face_value or 1000.0
        aci = bond.accrued_interest or 0.0
        price_pct = suggestion.suggested_price_pct or 100.0
        lot_size = bond.lot_size or 1
        return round(
            suggestion.lots * lot_size * (face * price_pct / 100.0 + aci),
            2,
        )
    return 0.0


def suggestion_to_session_item(
    suggestion: Suggestion,
    *,
    session_id: str,
    portfolio_id: str,
    universe_by_isin: dict[str, BondRecord],
) -> DeploySessionItem:
    item_id = stable_id(
        portfolio_id,
        "deploy-item",
        f"{session_id}:{suggestion.kind}:{_item_key(suggestion)}",
    )
    return DeploySessionItem(
        id=item_id,
        kind=suggestion.kind,  # type: ignore[arg-type]
        isin=suggestion.isin,
        name=suggestion.name,
        lots=suggestion.lots,
        figi=suggestion.figi,
        suggested_price_pct=float(suggestion.suggested_price_pct or 100.0),
        estimated_amount_rub=_estimated_amount_rub(suggestion, universe_by_isin),
        reason=suggestion.reason,
        source_isin=suggestion.source_isin,
        due_date=suggestion.due_date,
        urgency=suggestion.urgency,
    )


def build_deploy_session_plan(
    portfolio: Portfolio,
    holdings: list[HoldingView],
    positions: list[PortfolioPosition],
    universe: Sequence[BondRecord],
    *,
    available_cash: float,
    today: date,
    key_rate: float,
    tax_rate: float,
    selection_policy: BondSelectionPolicy = DEFAULT_BOND_SELECTION_POLICY,
    planning_policy: PlanningPolicy = DEFAULT_PLANNING_POLICY,
    duration_policy: DurationPolicy = DEFAULT_DURATION_POLICY,
    policy: DeploySessionPolicy = DeploySessionPolicy(),
    now: datetime | None = None,
    session_id: str | None = None,
) -> DeploySession:
    """Собрать снимок buy+reinvest рекомендаций для фиксации в сессии."""
    from bond_monitor.domain.trading.advisory import (
        build_buy_suggestions,
        build_reinvest_suggestions,
    )

    universe_by_isin = {bond.isin: bond for bond in universe}
    resolved_session_id = session_id or secrets.token_hex(16)
    created = now or datetime.now(UTC)
    expires = created + timedelta(hours=policy.ttl_hours)

    buy_suggestions = build_buy_suggestions(
        portfolio,
        holdings,
        universe,
        universe_by_isin,
        available_cash=available_cash,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        duration_policy=duration_policy,
    )
    reinvest_suggestions = build_reinvest_suggestions(
        portfolio,
        positions,
        universe,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
        policy=selection_policy,
        planning=planning_policy,
        duration_policy=duration_policy,
    )
    items = [
        suggestion_to_session_item(
            suggestion,
            session_id=resolved_session_id,
            portfolio_id=portfolio.id,
            universe_by_isin=universe_by_isin,
        )
        for suggestion in buy_suggestions + reinvest_suggestions
    ]
    return DeploySession(
        id=resolved_session_id,
        portfolio_id=portfolio.id,
        status="active",
        items=items,
        cash_snapshot_rub=available_cash,
        created_at=_as_utc(created),
        expires_at=_as_utc(expires),
    )


def session_item_to_suggestion(
    item: DeploySessionItem,
    universe_by_isin: dict[str, BondRecord],
) -> Suggestion:
    bond = universe_by_isin.get(item.isin)
    market_price = bond.last_price if bond is not None and bond.last_price else None
    return Suggestion(
        id=item.id,
        kind=item.kind,
        isin=item.isin,
        name=item.name,
        lots=item.lots,
        figi=item.figi,
        suggested_price_pct=item.suggested_price_pct,
        market_price_pct=market_price,
        reason=item.reason,
        due_date=item.due_date,
        source_isin=item.source_isin,
        urgency=item.urgency,
    )


def session_items_to_suggestions(
    session: DeploySession,
    universe: Sequence[BondRecord],
    *,
    kinds: set[DeploySessionItemKind],
) -> list[Suggestion]:
    """Преобразовать pending-позиции сессии в actionable suggestions."""
    universe_by_isin = {bond.isin: bond for bond in universe}
    result: list[Suggestion] = []
    for item in session.items:
        if item.kind not in kinds:
            continue
        if item.status != "pending":
            continue
        result.append(session_item_to_suggestion(item, universe_by_isin))
    return result


def _implied_market_price_pct(
    suggested_price_pct: float,
    account_kind,
) -> float:
    buffer = buy_limit_price_buffer(account_kind)
    return suggested_price_pct / (1 + buffer)


def apply_session_staleness(
    session: DeploySession,
    universe: Sequence[BondRecord],
    *,
    portfolio: Portfolio,
    policy: DeploySessionPolicy = DeploySessionPolicy(),
    now: datetime | None = None,
) -> DeploySession:
    """Проверить актуальность цен и доступность бумаг."""
    now = _as_utc(now or datetime.now(UTC))
    if _as_utc(session.expires_at) <= now:
        return replace(session, status="expired")

    universe_by_isin = {bond.isin: bond for bond in universe}
    warnings: list[str] = list(session.warnings)
    updated_items: list[DeploySessionItem] = []

    for item in session.items:
        if item.status in ("filled", "skipped", "stale", "placed"):
            updated_items.append(item)
            continue

        if item.kind == "reinvest" and item.due_date is not None:
            if item.due_date > now.date():
                updated_items.append(replace(item, status="stale"))
                warnings.append(
                    f"{item.name}: реинвестиция доступна с "
                    f"{item.due_date.strftime('%d.%m.%Y')} — обновите план ближе к дате"
                )
                continue
            if item.due_date < now.date():
                updated_items.append(replace(item, status="stale"))
                warnings.append(
                    f"{item.name}: погашение источника {item.due_date.strftime('%d.%m.%Y')} "
                    "прошло — обновите план"
                )
                continue

        bond = universe_by_isin.get(item.isin)
        if bond is None or not has_usable_price(bond):
            updated_items.append(replace(item, status="stale"))
            warnings.append(f"{item.isin}: бумага недоступна для покупки")
            continue

        implied_market = _implied_market_price_pct(
            item.suggested_price_pct,
            portfolio.account_kind,
        )
        current_market = bond.last_price or implied_market
        if implied_market <= 0:
            updated_items.append(item)
            continue

        drift_pct = abs(current_market - implied_market) / implied_market * 100.0
        if drift_pct >= policy.price_drift_stale_pct:
            updated_items.append(replace(item, status="stale"))
            warnings.append(
                f"{item.name}: цена ушла на {drift_pct:.1f}% — обновите план"
            )
        else:
            if drift_pct >= policy.price_drift_warn_pct:
                warnings.append(
                    f"{item.name}: цена изменилась на {drift_pct:.1f}%"
                )
            updated_items.append(item)

    deduped_warnings = list(dict.fromkeys(warnings))
    return replace(session, items=updated_items, warnings=deduped_warnings)


def sync_session_with_orders(
    session: DeploySession,
    active_orders: Sequence[BrokerActiveOrder],
) -> DeploySession:
    """Синхронизировать статусы items с активными заявками брокера."""
    orders_by_id = {order.order_id: order for order in active_orders}
    updated_items: list[DeploySessionItem] = []

    for item in session.items:
        if item.status != "placed" or not item.order_id:
            updated_items.append(item)
            continue

        order = orders_by_id.get(item.order_id)
        if order is None:
            updated_items.append(replace(item, status="filled"))
            continue

        if order.status == _FILLED_ORDER_STATUS:
            updated_items.append(replace(item, status="filled"))
        elif order.status in _TERMINAL_ORDER_STATUSES:
            updated_items.append(replace(item, status="pending", order_id=None))
        else:
            updated_items.append(item)

    session = replace(session, items=updated_items)
    return complete_session_if_no_pending(session)


def mark_item_placed(
    session: DeploySession,
    item_id: str,
    order_id: str,
) -> DeploySession:
    updated_items: list[DeploySessionItem] = []
    for item in session.items:
        if item.id == item_id:
            updated_items.append(
                replace(item, status="placed", order_id=order_id)
            )
        else:
            updated_items.append(item)
    session = replace(session, items=updated_items)
    return complete_session_if_no_pending(session)


def mark_item_skipped(session: DeploySession, item_id: str) -> DeploySession:
    updated_items: list[DeploySessionItem] = []
    for item in session.items:
        if item.id == item_id:
            updated_items.append(replace(item, status="skipped"))
        else:
            updated_items.append(item)
    session = replace(session, items=updated_items)
    return complete_session_if_no_pending(session)


def find_session_item(session: DeploySession, item_id: str) -> DeploySessionItem | None:
    for item in session.items:
        if item.id == item_id:
            return item
    return None


def complete_session_if_no_pending(session: DeploySession) -> DeploySession:
    """Завершить сессию, когда не осталось pending-позиций (placed = сделано для плана)."""
    if session.status != "active" or not session.items:
        return session
    if any(item.status == "pending" for item in session.items):
        return session
    return replace(
        session,
        status="completed",
        completed_at=datetime.now(UTC),
    )


def session_has_pending_items(session: DeploySession) -> bool:
    return any(item.status == "pending" for item in session.items)


def is_session_active(session: DeploySession, *, now: datetime | None = None) -> bool:
    now = _as_utc(now or datetime.now(UTC))
    return session.status == "active" and _as_utc(session.expires_at) > now
