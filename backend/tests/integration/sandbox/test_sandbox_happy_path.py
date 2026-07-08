"""
E2E smoke в T-Invest sandbox: broker API без stateful reconcile.

Сценарий:
1. open_sandbox_account → sandbox_pay_in
2. get_account_snapshot (пустой счёт)
3. post_limit_order BUY по цене ниже рынка
4. get_order_state
5. get_account_snapshot после заявки
6. cancel_order если заявка ещё активна
7. close_sandbox_account (finally)

Запуск: ``T_TRADING_TOKEN_SANDBOX=t.xxx pytest tests/integration/sandbox -m sandbox -k happy``
"""

from __future__ import annotations

import contextlib
import os
import time

import pytest

from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.domain.trading.models import AccountKind
from bond_monitor.infrastructure.tinvest.trading_client import (
    cancel_order,
    close_sandbox_account,
    get_account_snapshot,
    get_order_state,
    list_accounts,
    make_request_uid,
    open_sandbox_account,
    post_limit_order,
    sandbox_pay_in,
)

from .helpers import find_liquid_ofz

pytestmark = pytest.mark.sandbox

_SANDBOX_TOKEN: str = os.getenv("T_TRADING_TOKEN_SANDBOX", "").strip()
_SKIP_REASON = "T_TRADING_TOKEN_SANDBOX не задан — e2e в sandbox пропускается"


@pytest.mark.skipif(not _SANDBOX_TOKEN, reason=_SKIP_REASON)
def test_sandbox_happy_path() -> None:
    """Полный цикл sandbox: open → pay_in → BUY → state → snapshot → cancel → close."""
    token = _SANDBOX_TOKEN

    ofz = find_liquid_ofz(token)
    if ofz is None:
        pytest.skip("Не нашли ликвидную ОФЗ для теста (last_prices пусто)")
    figi, last_price_pct = ofz.figi, ofz.last_price_pct

    account_id = open_sandbox_account(token, name="bond-monitor-e2e")
    assert account_id, "open_sandbox_account вернул пустой account_id"

    try:
        accounts = list_accounts(token, AccountKind.SANDBOX)
        assert any(a.id == account_id for a in accounts)

        balance = sandbox_pay_in(token, account_id, Rub(100_000.0))
        assert balance > 0

        snapshot_before = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        assert snapshot_before.money_rub > 0
        assert not snapshot_before.bond_positions

        buy_price = PriceUnitPct(round(float(last_price_pct) * 0.95, 4))
        request_uid = make_request_uid(
            account_id=account_id,
            figi=figi,
            direction="BUY",
            lots=1,
            order_key="e2e-happy-path",
        )
        order = post_limit_order(
            token,
            AccountKind.SANDBOX,
            account_id=account_id,
            figi=figi,
            direction="BUY",
            lots=Lots(1),
            price_pct=buy_price,
            face_value=1000.0,
            request_uid=request_uid,
        )
        assert order.order_id
        assert order.request_uid == request_uid

        state = get_order_state(
            token,
            AccountKind.SANDBOX,
            account_id=account_id,
            order_id=order.order_id,
        )
        assert state.order_id == order.order_id
        assert state.direction == "BUY"

        snapshot_after = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        assert snapshot_after.money_rub >= 0

        terminal_statuses = {
            "EXECUTION_REPORT_STATUS_FILL",
            "EXECUTION_REPORT_STATUS_CANCELLED",
            "EXECUTION_REPORT_STATUS_REJECTED",
        }
        time.sleep(1)
        current_state = get_order_state(
            token,
            AccountKind.SANDBOX,
            account_id=account_id,
            order_id=order.order_id,
        )
        if current_state.execution_report_status not in terminal_statuses:
            cancelled = cancel_order(
                token,
                AccountKind.SANDBOX,
                account_id=account_id,
                order_id=order.order_id,
            )
            assert cancelled
    finally:
        with contextlib.suppress(Exception):
            close_sandbox_account(token, account_id)
