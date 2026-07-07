"""Применение и откат распределения top-up свободного кэша."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PositionSourceType,
)
from bond_monitor.domain.trading.models import PendingOperation
from bond_monitor.domain.portfolio.planner import TopUpAllocation
from bond_monitor.domain.portfolio.position_factory import position_from_bond


@dataclass(frozen=True)
class TopUpBatchMeta:
    """Метаданные волны top-up для отката."""

    previous_watermark: str | None
    distributed_amount_rub: float
    allocations: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_watermark": self.previous_watermark,
            "distributed_amount_rub": self.distributed_amount_rub,
            "allocations": list(self.allocations),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopUpBatchMeta:
        return cls(
            previous_watermark=(
                str(data["previous_watermark"]) if data.get("previous_watermark") else None
            ),
            distributed_amount_rub=float(data.get("distributed_amount_rub", 0.0)),
            allocations=list(data.get("allocations", [])),
        )


def has_active_top_up_batch(portfolio: Portfolio) -> bool:
    """Есть ли незакрытая волна top-up в сохранённых pending operations."""
    return any(op.kind == "top_up_buy" for op in portfolio.pending_operations)


def new_top_up_batch_id() -> str:
    return uuid.uuid4().hex[:16]


def apply_top_up_distribution(
    portfolio: Portfolio,
    allocations: list[TopUpAllocation],
    *,
    distributed_amount_rub: float,
    batch_id: str,
    processed_at_iso: str,
    universe_by_isin: dict[str, BondRecord],
    today: date,
) -> list[str]:
    """Применить аллокации top-up: обновить позиции и создать pending operations."""
    if not allocations:
        return ["Нет аллокаций для применения top-up."]

    previous_watermark = portfolio.last_top_up_processed_at
    rollback_allocations: list[dict[str, Any]] = []
    notes: list[str] = []

    for allocation in allocations:
        position = next((p for p in portfolio.positions if p.isin == allocation.isin), None)
        is_new_position = position is None
        if position is None:
            bond = universe_by_isin.get(allocation.isin)
            if bond is None:
                notes.append(f"Пропущена {allocation.isin}: бумага не найдена в universe.")
                continue
            position = position_from_bond(
                bond,
                lots=allocation.lots,
                purchase_date=today,
                source=PositionSourceType.INITIAL,
            )
            position.figi = allocation.figi
            portfolio.positions.append(position)
        else:
            underweight = (
                position.actual_lots is not None and position.actual_lots < position.lots
            )
            if not underweight:
                position.lots += allocation.lots

        rollback_allocations.append(
            {
                "isin": allocation.isin,
                "lots": allocation.lots,
                "is_new_position": is_new_position,
            }
        )

        portfolio.pending_operations.append(
            PendingOperation(
                kind="top_up_buy",
                isin=allocation.isin,
                name=allocation.name,
                lots=allocation.lots,
                figi=allocation.figi,
                suggested_price_pct=allocation.suggested_price_pct,
                estimated_amount_rub=allocation.estimated_amount_rub,
                top_up_batch_id=batch_id,
                reason="Пополнение счёта — автораспределение",
            )
        )

    portfolio.top_up_batch_meta[batch_id] = TopUpBatchMeta(
        previous_watermark=previous_watermark,
        distributed_amount_rub=distributed_amount_rub,
        allocations=rollback_allocations,
    ).to_dict()
    portfolio.acknowledged_top_ups_rub += distributed_amount_rub
    portfolio.last_top_up_processed_at = processed_at_iso
    notes.append(
        f"Автораспределение top-up: {distributed_amount_rub:,.0f} ₽ по "
        f"{len(rollback_allocations)} позициям."
    )
    return notes


def cancel_top_up_batch(portfolio: Portfolio, batch_id: str) -> None:
    """Откатить незавершённую волну top-up по batch_id."""
    raw_meta = portfolio.top_up_batch_meta.get(batch_id)
    if raw_meta is None:
        raise ValueError(f"Top-up batch {batch_id} not found")
    meta = TopUpBatchMeta.from_dict(raw_meta)

    for item in meta.allocations:
        isin = str(item["isin"])
        lots = int(item["lots"])
        is_new = bool(item.get("is_new_position"))
        position = next((p for p in portfolio.positions if p.isin == isin), None)
        if position is None:
            continue
        if is_new:
            portfolio.positions = [p for p in portfolio.positions if p.isin != isin]
        else:
            position.lots = max(0, position.lots - lots)
            if position.lots == 0:
                portfolio.positions = [p for p in portfolio.positions if p.isin != isin]

    portfolio.pending_operations = [
        op
        for op in portfolio.pending_operations
        if not (op.kind == "top_up_buy" and op.top_up_batch_id == batch_id)
    ]
    portfolio.acknowledged_top_ups_rub = max(
        0.0, portfolio.acknowledged_top_ups_rub - meta.distributed_amount_rub
    )
    portfolio.last_top_up_processed_at = meta.previous_watermark
    del portfolio.top_up_batch_meta[batch_id]


__all__ = [
    "TopUpBatchMeta",
    "apply_top_up_distribution",
    "cancel_top_up_batch",
    "has_active_top_up_batch",
    "new_top_up_batch_id",
]
