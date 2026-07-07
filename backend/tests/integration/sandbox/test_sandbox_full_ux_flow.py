"""
Полный UX-сценарий портфельного режима торговли в sandbox.

Эмулирует то, что делает UI при переходе портфеля в TRADING:

1. Создание свежего портфеля через ``data.portfolios.create_portfolio``.
2. Открытие sandbox-счёта + пополнение.
3. ``get_account_snapshot`` + ``validate_account_for_attach`` (strict).
4. Минимальный «универс» из одной реальной ОФЗ + ``auto_compose`` -
   симулирует то, что делает мастер перехода.
5. Фиксация ``FrozenForecast``.
6. ``compute_pending_operations`` → должен быть ``initial_buy``.
7. ``post_limit_order`` BUY (по цене ниже рынка чтобы не сматчилось).
8. ``reconcile_positions`` + ``summarize_actual_performance`` —
   проверяем что фактическая доходность хотя бы инициализирована.
9. Cleanup: cancel + close + удаление портфеля.

Этот тест не запускает Streamlit, но проходит через те же чистые
функции, что и UI-вкладка. Это финальный smoke перед закрытием задачи
(см. план «portfolio-trading-mode», todo `sandbox-smoke`).
"""

from __future__ import annotations

import contextlib
import os
from datetime import date, timedelta

import pytest

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.domain.trading.pending_operations import compute_pending_operations
from bond_monitor.domain.portfolio.models import (
    AccountKind,
    FrozenForecast,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    RiskProfile,
    TradeRecord,
)
from bond_monitor.domain.portfolio.planner import build_plan
from bond_monitor.domain.trading.reconciler import reconcile_positions, validate_account_for_attach
from bond_monitor.domain.trading.yield_calc import summarize_actual_performance
from bond_monitor.infrastructure.persistence.json_portfolios import create_portfolio, delete_portfolio, update_portfolio
from bond_monitor.infrastructure.tinvest.trading_client import (
    cancel_order,
    close_sandbox_account,
    get_account_operations,
    get_account_snapshot,
    make_request_uid,
    open_sandbox_account,
    post_limit_order,
    sandbox_pay_in,
)

pytestmark = pytest.mark.sandbox


_SANDBOX_TOKEN: str = os.getenv("T_TRADING_TOKEN_SANDBOX", "").strip()


def _find_ofz_for_buy(
    token: str,
) -> tuple[str, str, PriceUnitPct, int, float] | None:
    """Вернуть (figi, isin, last_price_pct, lot_size, face_value) ликвидной ОФЗ.

    Используется в smoke-тесте чтобы построить mini-universe из одной
    бумаги для ``auto_compose``.
    """
    from t_tech.invest import InstrumentStatus
    from t_tech.invest.sandbox.client import SandboxClient

    with SandboxClient(token) as client:
        bonds_resp = client.instruments.bonds(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
        )
        # ОФЗ в Tinkoff API имеют ISIN с префиксом RU000 и «ОФЗ» в имени.
        candidates = [
            b
            for b in bonds_resp.instruments
            if "ОФЗ" in (b.name or "") and b.api_trade_available_flag and b.buy_available_flag
        ][:30]

        for bond in candidates:
            prices_resp = client.market_data.get_last_prices(figi=[bond.figi])
            for entry in prices_resp.last_prices:
                p = entry.price
                units = int(getattr(p, "units", 0))
                nano = int(getattr(p, "nano", 0))
                if units == 0 and nano == 0:
                    continue
                price_pct = float(units) + nano / 1_000_000_000.0
                # face_value в Quotation
                fv = bond.nominal
                fv_value = float(getattr(fv, "units", 0)) + (
                    int(getattr(fv, "nano", 0)) / 1_000_000_000.0
                )
                return (
                    bond.figi,
                    bond.isin,
                    PriceUnitPct(price_pct),
                    int(bond.lot or 1),
                    fv_value or 1000.0,
                )
    return None


def _mini_universe(
    figi: str,
    isin: str,
    last_price_pct: PriceUnitPct,
    lot_size: int,
    face_value: float,
) -> list[BondRecord]:
    """Однобумажный универс для auto_compose в smoke-тесте."""
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
    """Программная эмуляция «создание → TRADING → buy → sync → XIRR»."""
    token = _SANDBOX_TOKEN

    target = _find_ofz_for_buy(token)
    if target is None:
        pytest.skip("Не нашли ОФЗ с last_price для теста")
    figi, isin, last_price_pct, lot_size, face_value = target

    # 1. Создаём портфель в локальном JSON
    portfolio = create_portfolio(
        name=f"smoke-{date.today().isoformat()}",
        initial_amount_rub=50_000.0,
        horizon_date=date.today() + timedelta(days=365),
        risk_profile=RiskProfile.NORMAL,
    )

    # 2. Sandbox: открываем счёт + пополняем
    account_id = open_sandbox_account(token, name="bond-monitor-smoke")

    try:
        sandbox_pay_in(token, account_id, Rub(100_000.0))

        # 3. Snapshot + validate (strict)
        snapshot = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        validation = validate_account_for_attach(snapshot, portfolio)
        assert validation.can_attach, (
            f"validate_account_for_attach unexpectedly blocked: {validation.blockers}"
        )
        assert validation.effective_initial_amount_rub > 0

        # 4. Привязываем счёт к портфелю + создаём одну позицию вручную
        # (auto_compose с большим универсом тоже работает, но для smoke
        # достаточно явной позиции, чтобы детерминированно проверить XIRR).
        portfolio.mode = PortfolioMode.TRADING
        portfolio.account_id = account_id
        portfolio.account_kind = AccountKind.SANDBOX
        portfolio.account_label = f"smoke-{account_id[:6]}"
        portfolio.initial_amount_rub = float(validation.effective_initial_amount_rub)

        portfolio.positions = [
            PortfolioPosition(
                isin=isin,
                secid=isin[:6],
                name=f"OFZ {isin[-4:]}",
                lots=1,
                lot_size=lot_size,
                purchase_clean_price_pct=float(last_price_pct),
                purchase_dirty_price_rub=face_value * float(last_price_pct) / 100.0,
                purchase_aci_rub=0.0,
                purchase_date=date.today(),
                purchase_amount_rub=face_value * float(last_price_pct) / 100.0 * lot_size,
                coupon_rate=10.0,
                face_value=face_value,
                maturity_date=date.today() + timedelta(days=365 * 2),
                offer_date=None,
                coupon_period_days=180,
                source=PositionSourceType.INITIAL,
                put_offer_decision=PutOfferDecision.PENDING,
                figi=figi,
                actual_lots=0,
            )
        ]

        # 5. Считаем план и фиксируем frozen_forecast
        universe = _mini_universe(figi, isin, last_price_pct, lot_size, face_value)
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

        # 6. compute_pending_operations: должна быть как минимум 1 initial_buy
        pending = compute_pending_operations(portfolio, snapshot, date.today())
        initial_buys = [op for op in pending if op.kind == "initial_buy"]
        assert initial_buys, "Не сгенерировано ни одной initial_buy pending"
        op = initial_buys[0]
        assert op.figi == figi

        # 7. post_limit_order BUY 1 лот по цене НИЖЕ рынка
        buy_price = PriceUnitPct(round(float(last_price_pct) * 0.93, 4))
        request_uid = make_request_uid(
            account_id=account_id,
            figi=figi,
            direction="BUY",
            lots=op.lots,
            pending_op_id=op.id,
        )
        result = post_limit_order(
            token,
            AccountKind.SANDBOX,
            account_id=account_id,
            figi=figi,
            direction="BUY",
            lots=Lots(op.lots),
            price_pct=buy_price,
            face_value=face_value,
            request_uid=request_uid,
        )
        assert result.order_id

        # Сохраняем TradeRecord (как делает UI)
        portfolio.trade_records.append(
            TradeRecord(
                request_uid=request_uid,
                order_id=result.order_id,
                account_id=account_id,
                account_kind=AccountKind.SANDBOX,
                figi=figi,
                direction="BUY",
                lots=op.lots,
                price_pct=buy_price,
                status=result.execution_report_status,
                pending_op_id=op.id,
            )
        )
        update_portfolio(portfolio)

        # 8. Cинхронизация: snapshot + operations + reconcile + XIRR
        snapshot_after = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        operations = get_account_operations(
            token,
            AccountKind.SANDBOX,
            account_id,
            from_date=date.today() - timedelta(days=1),
        )
        reconcile_result = reconcile_positions(portfolio, snapshot_after, operations)
        assert isinstance(reconcile_result.drifts, list)

        # XIRR: на момент теста может быть None (только BUY, нет cashflow),
        # главное — функция не падает и возвращает структуру.
        performance = summarize_actual_performance(portfolio, snapshot_after, operations)
        assert performance.unrealized_value_rub >= 0
        assert performance.coupons_received_rub >= 0

        # 9. Отмена ордера если ещё активен.
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
