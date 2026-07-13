"""Map deploy session domain model to API DTOs."""

from __future__ import annotations

from bond_monitor.application.trading.types import (
    DeploySessionItemResponse,
    DeploySessionProgressResponse,
    DeploySessionResponse,
)
from bond_monitor.domain.trading.deploy_session import DeploySession, deploy_session_progress


def deploy_session_to_response(session: DeploySession) -> DeploySessionResponse:
    progress = deploy_session_progress(session)
    return DeploySessionResponse(
        id=session.id,
        status=session.status,
        expires_at=session.expires_at.isoformat(),
        cash_snapshot_rub=session.cash_snapshot_rub,
        progress=DeploySessionProgressResponse(
            total=progress.total,
            pending=progress.pending,
            placed=progress.placed,
            filled=progress.filled,
            skipped=progress.skipped,
            stale=progress.stale,
        ),
        items=[
            DeploySessionItemResponse(
                id=item.id,
                kind=item.kind,
                isin=item.isin,
                name=item.name,
                lots=item.lots,
                figi=item.figi,
                suggested_price_pct=item.suggested_price_pct,
                estimated_amount_rub=item.estimated_amount_rub,
                reason=item.reason,
                status=item.status,
                source_isin=item.source_isin,
                due_date=item.due_date.isoformat() if item.due_date else None,
                order_id=item.order_id,
                urgency=item.urgency,
            )
            for item in session.items
        ],
        warnings=list(session.warnings),
    )
