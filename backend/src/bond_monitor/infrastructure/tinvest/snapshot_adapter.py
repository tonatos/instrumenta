"""Map infrastructure broker types to domain ports."""

from __future__ import annotations

from bond_monitor.domain.trading.ports import (
    BrokerActiveOrder,
    BrokerBondPosition,
    BrokerOperation,
    BrokerOtherInstrument,
    BrokerSnapshot,
)
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    BondPosition,
    OperationRecord,
    OrderState,
    OtherInstrument,
)


def broker_snapshot_from_infrastructure(snapshot: AccountSnapshot) -> BrokerSnapshot:
    return BrokerSnapshot(
        account_id=snapshot.account_id,
        account_kind=snapshot.account_kind,
        money_rub=snapshot.money_rub,
        blocked_money_rub=snapshot.blocked_money_rub,
        bond_positions={
            figi: _bond_position_from_infrastructure(pos)
            for figi, pos in snapshot.bond_positions.items()
        },
        other_instruments=[
            _other_instrument_from_infrastructure(ins) for ins in snapshot.other_instruments
        ],
        fetched_at=snapshot.fetched_at,
    )


def broker_operation_from_infrastructure(operation: OperationRecord) -> BrokerOperation:
    return BrokerOperation(
        id=operation.id,
        type=operation.type,
        state=operation.state,
        date=operation.date,
        figi=operation.figi,
        instrument_uid=operation.instrument_uid,
        instrument_type=operation.instrument_type,
        payment_rub=operation.payment_rub,
        quantity=operation.quantity,
        price_pct=operation.price_pct,
        commission_rub=operation.commission_rub,
    )


def broker_operations_from_infrastructure(
    operations: list[OperationRecord],
) -> list[BrokerOperation]:
    return [broker_operation_from_infrastructure(op) for op in operations]


def _bond_position_from_infrastructure(position: BondPosition) -> BrokerBondPosition:
    return BrokerBondPosition(
        figi=position.figi,
        instrument_uid=position.instrument_uid,
        ticker=position.ticker,
        quantity=position.quantity,
        lots=position.lots,
        blocked=position.blocked,
        current_price_pct=position.current_price_pct,
        current_nkd_rub=position.current_nkd_rub,
        average_price_pct=position.average_price_pct,
    )


def broker_active_orders_from_infrastructure(orders: list[OrderState]) -> list[BrokerActiveOrder]:
    result: list[BrokerActiveOrder] = []
    for order in orders:
        result.append(
            BrokerActiveOrder(
                order_id=order.order_id,
                request_uid=order.request_uid,
                figi=order.figi,
                direction=order.direction,
                lots_requested=order.lots_requested,
                lots_executed=order.lots_executed,
                status=order.execution_report_status,
                price_pct=float(order.price_pct) if order.price_pct is not None else None,
                total_order_amount_rub=(
                    float(order.total_order_amount_rub)
                    if order.total_order_amount_rub is not None
                    else None
                ),
                initial_commission_rub=(
                    float(order.initial_commission_rub)
                    if order.initial_commission_rub is not None
                    else None
                ),
            )
        )
    return result
