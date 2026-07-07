"""Доменные модели режима торговли."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4


class AccountKind(StrEnum):
    """Контур T-Invest API: sandbox (виртуальные деньги) или production."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"


ACCOUNT_KIND_LABELS: dict[AccountKind, str] = {
    AccountKind.SANDBOX: "Песочница",
    AccountKind.PRODUCTION: "Боевой",
}


PendingOperationKind = Literal[
    "initial_buy",
    "reinvest_buy",
    "top_up_buy",
    "put_offer_submit",
    "manual_sell",
]

PendingOperationStatus = Literal["action_required", "in_progress", "overdue", "blocked"]
PendingOperationUrgency = Literal["normal", "soon", "critical"]

OrderDirection = Literal["BUY", "SELL"]


def _new_op_id() -> str:
    """UUID4 hex для PendingOperation / TradeRecord — короткий, JSON-friendly."""
    return uuid4().hex


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class FrozenForecast:
    """Скалярный снимок прогноза доходности в момент перехода в режим торговли."""

    expected_xirr_pct: float | None
    expected_total_net_profit_rub: float
    expected_final_value_rub: float
    frozen_initial_amount_rub: float
    horizon_date: date
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_xirr_pct": self.expected_xirr_pct,
            "expected_total_net_profit_rub": self.expected_total_net_profit_rub,
            "expected_final_value_rub": self.expected_final_value_rub,
            "frozen_initial_amount_rub": self.frozen_initial_amount_rub,
            "horizon_date": self.horizon_date.isoformat(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrozenForecast:
        xirr = data.get("expected_xirr_pct")
        return cls(
            expected_xirr_pct=float(xirr) if xirr is not None else None,
            expected_total_net_profit_rub=float(data.get("expected_total_net_profit_rub", 0.0)),
            expected_final_value_rub=float(data.get("expected_final_value_rub", 0.0)),
            frozen_initial_amount_rub=float(data.get("frozen_initial_amount_rub", 0.0)),
            horizon_date=date.fromisoformat(str(data["horizon_date"])),
            created_at=str(data.get("created_at") or _utc_now_iso()),
        )


@dataclass
class PendingOperation:
    """Операция, ожидающая подтверждения пользователя в режиме торговли."""

    kind: PendingOperationKind
    isin: str
    name: str
    lots: int
    id: str = field(default_factory=_new_op_id)
    figi: str | None = None
    suggested_price_pct: float | None = None
    due_date: date | None = None
    reason: str = ""
    slot_id: str | None = None
    top_up_batch_id: str | None = None
    submitted_request_uid: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    status: PendingOperationStatus = "action_required"
    block_reason: str | None = None
    estimated_amount_rub: float | None = None
    face_value_rub: float | None = None
    lot_size: int | None = None
    aci_rub_per_bond: float | None = None
    active_order_id: str | None = None
    active_order_status: str | None = None
    active_order_lots: int | None = None
    active_order_price_pct: float | None = None
    active_order_total_rub: float | None = None
    active_order_commission_rub: float | None = None
    active_order_lots_executed: int | None = None
    active_order_bonds_count: int | None = None
    urgency: PendingOperationUrgency = "normal"
    chat_template: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "isin": self.isin,
            "name": self.name,
            "lots": self.lots,
            "figi": self.figi,
            "suggested_price_pct": self.suggested_price_pct,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "reason": self.reason,
            "slot_id": self.slot_id,
            "top_up_batch_id": self.top_up_batch_id,
            "submitted_request_uid": self.submitted_request_uid,
            "created_at": self.created_at,
            "status": self.status,
            "block_reason": self.block_reason,
            "estimated_amount_rub": self.estimated_amount_rub,
            "face_value_rub": self.face_value_rub,
            "lot_size": self.lot_size,
            "aci_rub_per_bond": self.aci_rub_per_bond,
            "active_order_id": self.active_order_id,
            "active_order_status": self.active_order_status,
            "active_order_lots": self.active_order_lots,
            "active_order_price_pct": self.active_order_price_pct,
            "active_order_total_rub": self.active_order_total_rub,
            "active_order_commission_rub": self.active_order_commission_rub,
            "active_order_lots_executed": self.active_order_lots_executed,
            "active_order_bonds_count": self.active_order_bonds_count,
            "urgency": self.urgency,
            "chat_template": self.chat_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingOperation:
        kind_raw = str(data.get("kind", "initial_buy"))
        if kind_raw not in (
            "initial_buy",
            "reinvest_buy",
            "top_up_buy",
            "put_offer_submit",
            "manual_sell",
        ):
            raise ValueError(f"Unknown PendingOperation kind: {kind_raw!r}")
        return cls(
            id=str(data.get("id") or _new_op_id()),
            kind=kind_raw,  # type: ignore[arg-type]
            isin=str(data["isin"]),
            name=str(data.get("name", "")),
            lots=int(data.get("lots", 0)),
            figi=(str(data["figi"]) if data.get("figi") else None),
            suggested_price_pct=(
                float(data["suggested_price_pct"])
                if data.get("suggested_price_pct") is not None
                else None
            ),
            due_date=(date.fromisoformat(str(data["due_date"])) if data.get("due_date") else None),
            reason=str(data.get("reason", "")),
            slot_id=(str(data["slot_id"]) if data.get("slot_id") else None),
            top_up_batch_id=(str(data["top_up_batch_id"]) if data.get("top_up_batch_id") else None),
            submitted_request_uid=(
                str(data["submitted_request_uid"]) if data.get("submitted_request_uid") else None
            ),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            status=str(data.get("status", "action_required")),  # type: ignore[arg-type]
            block_reason=(str(data["block_reason"]) if data.get("block_reason") else None),
            estimated_amount_rub=(
                float(data["estimated_amount_rub"])
                if data.get("estimated_amount_rub") is not None
                else None
            ),
            face_value_rub=(
                float(data["face_value_rub"]) if data.get("face_value_rub") is not None else None
            ),
            lot_size=int(data["lot_size"]) if data.get("lot_size") is not None else None,
            aci_rub_per_bond=(
                float(data["aci_rub_per_bond"])
                if data.get("aci_rub_per_bond") is not None
                else None
            ),
            active_order_id=(str(data["active_order_id"]) if data.get("active_order_id") else None),
            active_order_status=(
                str(data["active_order_status"]) if data.get("active_order_status") else None
            ),
            active_order_lots=(
                int(data["active_order_lots"]) if data.get("active_order_lots") is not None else None
            ),
            active_order_price_pct=(
                float(data["active_order_price_pct"])
                if data.get("active_order_price_pct") is not None
                else None
            ),
            active_order_total_rub=(
                float(data["active_order_total_rub"])
                if data.get("active_order_total_rub") is not None
                else None
            ),
            active_order_commission_rub=(
                float(data["active_order_commission_rub"])
                if data.get("active_order_commission_rub") is not None
                else None
            ),
            active_order_lots_executed=(
                int(data["active_order_lots_executed"])
                if data.get("active_order_lots_executed") is not None
                else None
            ),
            active_order_bonds_count=(
                int(data["active_order_bonds_count"])
                if data.get("active_order_bonds_count") is not None
                else None
            ),
            urgency=str(data.get("urgency", "normal")),  # type: ignore[arg-type]
            chat_template=(str(data["chat_template"]) if data.get("chat_template") else None),
        )


@dataclass
class TradeRecord:
    """Аудит-запись отправленной/отменённой заявки T-Invest API."""

    request_uid: str
    account_id: str
    account_kind: AccountKind
    figi: str
    direction: OrderDirection
    lots: int
    pending_op_id: str | None = None
    order_id: str | None = None
    price_pct: float | None = None
    status: str = "EXECUTION_REPORT_STATUS_NEW"
    submitted_at: str = field(default_factory=_utc_now_iso)
    last_state_checked_at: str | None = None
    total_order_amount_rub: float | None = None
    initial_commission_rub: float | None = None
    lots_executed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_uid": self.request_uid,
            "account_id": self.account_id,
            "account_kind": self.account_kind.value,
            "figi": self.figi,
            "direction": self.direction,
            "lots": self.lots,
            "pending_op_id": self.pending_op_id,
            "order_id": self.order_id,
            "price_pct": self.price_pct,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "last_state_checked_at": self.last_state_checked_at,
            "total_order_amount_rub": self.total_order_amount_rub,
            "initial_commission_rub": self.initial_commission_rub,
            "lots_executed": self.lots_executed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeRecord:
        direction_raw = str(data.get("direction", "BUY"))
        if direction_raw not in ("BUY", "SELL"):
            raise ValueError(f"Unknown TradeRecord direction: {direction_raw!r}")
        return cls(
            request_uid=str(data["request_uid"]),
            account_id=str(data["account_id"]),
            account_kind=AccountKind(data.get("account_kind", AccountKind.SANDBOX.value)),
            figi=str(data["figi"]),
            direction=direction_raw,  # type: ignore[arg-type]
            lots=int(data["lots"]),
            pending_op_id=(str(data["pending_op_id"]) if data.get("pending_op_id") else None),
            order_id=(str(data["order_id"]) if data.get("order_id") else None),
            price_pct=(float(data["price_pct"]) if data.get("price_pct") is not None else None),
            status=str(data.get("status", "EXECUTION_REPORT_STATUS_NEW")),
            submitted_at=str(data.get("submitted_at") or _utc_now_iso()),
            last_state_checked_at=(
                str(data["last_state_checked_at"]) if data.get("last_state_checked_at") else None
            ),
            total_order_amount_rub=(
                float(data["total_order_amount_rub"])
                if data.get("total_order_amount_rub") is not None
                else None
            ),
            initial_commission_rub=(
                float(data["initial_commission_rub"])
                if data.get("initial_commission_rub") is not None
                else None
            ),
            lots_executed=int(data.get("lots_executed", 0)),
        )

    @property
    def is_active(self) -> bool:
        """Заявка ещё на бирже (не исполнена, не отменена, не отклонена)."""
        terminal = {
            "EXECUTION_REPORT_STATUS_FILL",
            "EXECUTION_REPORT_STATUS_CANCELLED",
            "EXECUTION_REPORT_STATUS_REJECTED",
        }
        return self.status not in terminal
