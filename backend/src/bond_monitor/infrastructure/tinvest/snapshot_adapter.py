"""Map infrastructure broker types to domain ports."""

from __future__ import annotations

from bond_monitor.domain.trading.ports import (
    BrokerBondPosition,
    BrokerOperation,
    BrokerOtherInstrument,
    BrokerSnapshot,
)
from bond_monitor.infrastructure.tinvest.trading_client import (
    AccountSnapshot,
    BondPosition,
    OperationRecord,
    OtherInstrument,
)


def broker_snapshot_from_infrastructure(snapshot: AccountSnapshot) -> BrokerSnapshot:
    return BrokerSnapshot(
        account_id=snapshot.account_id,
        account_kind=snapshot.account_kind,
        money_rub=snapshot.money_rub,
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


def _other_instrument_from_infrastructure(instrument: OtherInstrument) -> BrokerOtherInstrument:
    return BrokerOtherInstrument(
        instrument_type=instrument.instrument_type,
        figi=instrument.figi,
        ticker=instrument.ticker,
        quantity=instrument.quantity,
    )
