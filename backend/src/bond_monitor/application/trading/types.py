"""Shared DTOs for trading application layer."""

from __future__ import annotations

from dataclasses import dataclass, field

from bond_monitor.interfaces.schemas.api import PendingOperationResponse


@dataclass
class TradingSyncResult:
    """Результат синхронизации портфеля со счётом T-Invest."""

    pending_operations: list[PendingOperationResponse]
    drifts: list[dict]
    money_rub: float
    last_synced_at: str | None
    has_pending_top_up: bool = False
    pending_top_up_rub: float = 0.0
    top_up_auto_applied: bool = False
    top_up_distributed_rub: float = 0.0
    top_up_notes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class OrderPreviewResult:
    """Превью стоимости заявки до подтверждения."""

    order_lots: int
    order_bonds: int
    lot_size: int
    order_price_pct: float
    clean_amount_rub: float
    aci_rub_per_bond: float
    local_total_amount_rub: float
    broker_clean_amount_rub: float | None
    broker_aci_amount_rub: float | None
    broker_total_amount_rub: float | None
    broker_commission_rub: float | None
    money_rub: float
    sufficient_cash: bool
    preview_source: str = "moex"
