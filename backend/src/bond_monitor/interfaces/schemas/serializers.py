"""Serialize domain objects to API DTOs."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.invested_capital import invested_capital_rub
from bond_monitor.domain.portfolio.cashflow import cashflow_rows_with_balance
from bond_monitor.domain.portfolio.models import Portfolio
from bond_monitor.domain.portfolio.planner import PortfolioPlan
from bond_monitor.domain.portfolio.position_status import open_positions, position_to_api_dict
from bond_monitor.domain.shared.money import bond_clean_price_pct_from_rub
from bond_monitor.domain.trading.operation_labels import (
    operation_state_label,
    operation_type_label,
)
from bond_monitor.infrastructure.tinvest.trading_client import OperationRecord
from bond_monitor.interfaces.schemas.api import (
    AccountOperationResponse,
    BondResponse,
    PlanResponse,
    PortfolioDataResponse,
    PortfolioResponse,
)


def bond_to_response(bond: BondRecord) -> BondResponse:
    return BondResponse(
        secid=bond.secid,
        isin=bond.isin,
        name=bond.name,
        figi=bond.figi,
        maturity_date=bond.maturity_date,
        offer_date=bond.offer_date,
        call_date=bond.call_date,
        effective_date=bond.effective_date,
        days_to_maturity=bond.days_to_maturity,
        ytm=bond.ytm,
        ytm_net=bond.ytm_net,
        coupon_rate=bond.coupon_rate,
        coupon_type=bond.coupon_type.value,
        last_price=bond.last_price,
        face_value=bond.face_value,
        lot_size=bond.lot_size,
        duration_years=bond.duration_years,
        volume_rub=bond.volume_rub,
        prev_volume_rub=bond.prev_volume_rub,
        credit_rating=bond.credit_rating,
        risk_level=int(bond.risk_level),
        score=bond.score,
        ytm_score=bond.ytm_score,
        risk_score=bond.risk_score,
        liquidity_score=bond.liquidity_score,
        is_favorite=bond.is_favorite,
        has_warnings=bond.has_warnings,
        warnings=bond.warnings_list(),
        tinvest_enriched=bond.tinvest_enriched,
        issuer_name=bond.issuer_name,
        instrument_full_name=bond.instrument_full_name,
        sector=bond.sector,
        description=bond.description,
    )


def portfolio_to_response(portfolio: Portfolio, *, today: date | None = None) -> PortfolioResponse:
    today = today or date.today()
    d = portfolio.to_dict()
    d["positions"] = [
        position_to_api_dict(p, is_trading=portfolio.is_trading, today=today)
        for p in portfolio.positions
    ]
    open_count = len(open_positions(portfolio.positions))
    closed_count = len(portfolio.positions) - open_count
    d["closed_positions_count"] = closed_count
    data = PortfolioDataResponse.model_validate(d)
    capital = invested_capital_rub(portfolio)
    return PortfolioResponse(
        id=portfolio.id,
        name=portfolio.name,
        initial_amount_rub=portfolio.initial_amount_rub,
        horizon_date=portfolio.horizon_date,
        risk_profile=portfolio.risk_profile.value,
        cash_balance_rub=portfolio.cash_balance_rub,
        mode=portfolio.mode.value,
        account_id=portfolio.account_id,
        account_kind=portfolio.account_kind.value if portfolio.account_kind else None,
        positions_count=open_count,
        closed_positions_count=closed_count,
        invested_capital_rub=capital,
        data=data,
    )


def plan_to_response(plan: PortfolioPlan) -> PlanResponse:
    return PlanResponse(
        total_net_profit_rub=plan.total_net_profit_rub,
        total_net_profit_with_held_rub=plan.total_net_profit_with_held_rub,
        invested_capital_rub=plan.invested_capital_rub,
        total_invested_rub=plan.total_invested_rub,
        final_cash_balance=plan.final_cash_balance_rub,
        final_portfolio_value=plan.final_portfolio_value_rub,
        initial_cash_rub=plan.initial_cash_rub,
        expected_xirr_pct=plan.effective_annual_return_pct,
        weighted_duration_years=plan.weighted_duration_years,
        notes=list(plan.notes),
        cashflow=cashflow_rows_with_balance(plan.events, plan.initial_cash_rub),
        value_timeline=[
            {
                "date": p.date.isoformat(),
                "cash_rub": p.cash_rub,
                "positions_value_rub": p.positions_value_rub,
                "total_value_rub": p.total_value_rub,
            }
            for p in plan.value_timeline
        ],
        held_positions=[
            {
                "isin": h.position.isin,
                "name": h.position.name,
                "lots": h.position.lots,
                "estimated_value_rub": h.estimated_value_rub,
                "maturity_date": (
                    h.position.maturity_date.isoformat() if h.position.maturity_date else None
                ),
            }
            for h in plan.held_positions
        ],
        slots=[s.to_plan_dict() for s in plan.resolved_slots],
    )


def account_operation_to_response(
    operation: OperationRecord,
    *,
    bonds_by_figi: dict[str, BondRecord],
) -> AccountOperationResponse:
    bond = bonds_by_figi.get(operation.figi) if operation.figi else None
    price_pct: float | None = None
    if operation.price_pct is not None:
        raw_price = float(operation.price_pct)
        if (
            operation.instrument_type == "bond"
            and bond is not None
            and bond.face_value is not None
            and bond.face_value > 0
        ):
            # T-Invest отдаёт цену сделки в ₽ за облигацию, не в % от номинала.
            price_pct = float(
                bond_clean_price_pct_from_rub(
                    clean_price_rub=raw_price,
                    face_value=bond.face_value,
                )
            )
        else:
            price_pct = raw_price
    return AccountOperationResponse(
        id=operation.id,
        type=operation.type,
        type_label=operation_type_label(operation.type),
        state=operation.state,
        state_label=operation_state_label(operation.state),
        date=operation.date.isoformat(),
        figi=operation.figi,
        instrument_type=operation.instrument_type,
        isin=bond.isin if bond is not None else None,
        name=bond.name if bond is not None else None,
        payment_rub=float(operation.payment_rub) if operation.payment_rub is not None else None,
        quantity=operation.quantity,
        price_pct=price_pct,
        commission_rub=(
            float(operation.commission_rub) if operation.commission_rub is not None else None
        ),
    )
