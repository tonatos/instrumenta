"""
Полный UX-сценарий trading-портфеля в sandbox (stateless advisory).

1. create_portfolio → sandbox open + pay_in
2. validate_attach_soft + attach
3. build_plan + frozen_forecast
4. advise() → buy suggestion
5. post_limit_order по рекомендации
6. advise() с active_orders + summarize_actual_performance
7. cancel + cleanup
"""

from __future__ import annotations

import contextlib
import os
from datetime import date, timedelta

import pytest

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import PortfolioMode, RiskProfile
from bond_monitor.domain.portfolio.planner import build_plan
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.domain.trading.advisory import advise, validate_attach_soft
from bond_monitor.domain.trading.models import AccountKind, FrozenForecast
from bond_monitor.domain.trading.yield_calc import summarize_actual_performance
from bond_monitor.infrastructure.persistence.json_portfolios import create_portfolio, delete_portfolio, update_portfolio
from bond_monitor.infrastructure.tinvest.trading_client import (
    cancel_order,
    close_sandbox_account,
    get_account_operations,
    get_account_snapshot,
    get_active_orders,
    make_request_uid,
    open_sandbox_account,
    post_limit_order,
    sandbox_pay_in,
)

from .helpers import find_liquid_ofz

pytestmark = pytest.mark.sandbox

_SANDBOX_TOKEN: str = os.getenv("T_TRADING_TOKEN_SANDBOX", "").strip()


def _mini_universe(
    figi: str,
    isin: str,
    last_price_pct: PriceUnitPct,
    lot_size: int,
    face_value: float,
) -> list[BondRecord]:
    today = date.today()
    bond = BondRecord(
        secid=isin[:6],
        isin=isin,
        name=f"OFZ {isin[-4:]}",
        maturity_date=today + timedelta(days=730),
        last_price=float(last_price_pct),
        face_value=face_value,
        lot_size=lot_size,
        coupon_rate=10.0,
        coupon_period_days=180,
        volume_rub=10_000_000.0,
        liquidity_flag=True,
        credit_rating="ruAAA",
        risk_level=RiskLevel.LOW,
        ytm=12.0,
        ytm_net=10.0,
    )
    bond.figi = figi
    bond.accrued_interest = 0.0
    return [bond]


@pytest.mark.skipif(not _SANDBOX_TOKEN, reason="T_TRADING_TOKEN_SANDBOX не задан")
def test_full_ux_flow_in_sandbox() -> None:
    """Программная эмуляция: create → TRADING → advise → buy → performance."""
    token = _SANDBOX_TOKEN

    ofz = find_liquid_ofz(token)
    if ofz is None:
        pytest.skip("Не нашли ОФЗ с last_price для теста")
    figi, isin, last_price_pct, lot_size, face_value = (
        ofz.figi,
        ofz.isin,
        ofz.last_price_pct,
        ofz.lot_size,
        ofz.face_value,
    )

    portfolio = create_portfolio(
        name=f"smoke-{date.today().isoformat()}",
        initial_amount_rub=50_000.0,
        horizon_date=date.today() + timedelta(days=365),
        risk_profile=RiskProfile.NORMAL,
    )

    account_id = open_sandbox_account(token, name="bond-monitor-smoke")

    try:
        sandbox_pay_in(token, account_id, Rub(100_000.0))

        snapshot = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        universe = _mini_universe(figi, isin, last_price_pct, lot_size, face_value)
        validation = validate_attach_soft(snapshot, portfolio, universe)
        assert validation.can_attach
        assert validation.effective_initial_amount_rub > 0

        portfolio.mode = PortfolioMode.TRADING
        portfolio.account_id = account_id
        portfolio.account_kind = AccountKind.SANDBOX
        portfolio.account_label = f"smoke-{account_id[:6]}"
        portfolio.initial_amount_rub = float(validation.effective_initial_amount_rub)
        portfolio.trading_started_at = date.today().isoformat()

        plan = build_plan(
            portfolio,
            universe,
            today=date.today(),
            key_rate=16.0,
            tax_rate=0.13,
            account_snapshot_money_rub=snapshot.money_rub,
        )
        portfolio.frozen_forecast = FrozenForecast(
            expected_xirr_pct=plan.effective_annual_return_pct,
            expected_total_net_profit_rub=plan.total_net_profit_with_held_rub,
            expected_final_value_rub=plan.final_portfolio_value_rub,
            frozen_initial_amount_rub=portfolio.initial_amount_rub,
            horizon_date=portfolio.horizon_date,
        )
        update_portfolio(portfolio)

        advice_before = advise(
            portfolio,
            snapshot,
            active_orders=[],
            operations=[],
            universe=universe,
            key_rate=16.0,
            tax_rate=0.13,
            today=date.today(),
        )
        buy_suggestions = [s for s in advice_before.suggestions if s.kind == "buy"]
        assert buy_suggestions, "advise() должен предложить покупку при свободном кэше"
        suggestion = buy_suggestions[0]
        assert suggestion.lots >= 1

        buy_price = PriceUnitPct(round(float(last_price_pct) * 0.93, 4))
        order_figi = suggestion.figi or figi
        request_uid = make_request_uid(
            account_id=account_id,
            figi=order_figi,
            direction="BUY",
            lots=suggestion.lots,
            order_key=suggestion.id,
        )
        result = post_limit_order(
            token,
            AccountKind.SANDBOX,
            account_id=account_id,
            figi=order_figi,
            direction="BUY",
            lots=Lots(suggestion.lots),
            price_pct=buy_price,
            face_value=face_value,
            request_uid=request_uid,
        )
        assert result.order_id

        snapshot_after = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        operations = get_account_operations(
            token,
            AccountKind.SANDBOX,
            account_id,
            from_date=date.today() - timedelta(days=1),
        )
        active_orders = get_active_orders(token, AccountKind.SANDBOX, account_id)

        advice_after = advise(
            portfolio,
            snapshot_after,
            active_orders=active_orders,
            operations=operations,
            universe=universe,
            key_rate=16.0,
            tax_rate=0.13,
            today=date.today(),
        )
        assert advice_after.performance is not None
        assert advice_after.available_money_rub >= 0

        performance = summarize_actual_performance(portfolio, snapshot_after, operations)
        assert performance.unrealized_value_rub >= 0
        assert performance.coupons_received_rub >= 0

        terminal = {
            "EXECUTION_REPORT_STATUS_FILL",
            "EXECUTION_REPORT_STATUS_CANCELLED",
            "EXECUTION_REPORT_STATUS_REJECTED",
        }
        if result.execution_report_status not in terminal:
            cancel_order(
                token,
                AccountKind.SANDBOX,
                account_id=account_id,
                order_id=result.order_id,
            )
    finally:
        with contextlib.suppress(Exception):
            close_sandbox_account(token, account_id)
        with contextlib.suppress(Exception):
            delete_portfolio(portfolio.id)
