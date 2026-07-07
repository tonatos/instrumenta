"""
E2E-тест happy-path в T-Invest sandbox.

Скип, если в окружении нет `T_TRADING_TOKEN_SANDBOX`. Это сознательная
архитектура: e2e тест дорогой (открывает реальный sandbox-счёт через
сеть) и нужен только для смоук-проверки интеграции. Юнит-тесты
покрывают всю чистую логику в отрыве от API.

Сценарий:

1. ``open_sandbox_account`` → новый ``account_id``
2. ``sandbox_pay_in`` 100 000 ₽
3. Найти любую ликвидную ОФЗ через ``instruments.bonds`` + ``market_data``
4. ``post_limit_order`` BUY на 1 лот по цене ниже рынка (чтобы не
   сматчилось мгновенно — позволит проверить cancel)
5. ``get_order_state`` → одной попытки достаточно для проверки контракта
6. ``get_account_snapshot`` → должен быть валидный объект
7. ``reconcile_positions`` → структура drifts не падает
8. ``cancel_order`` если заявка ещё активна
9. ``close_sandbox_account`` (даже при ошибке выше — через finally)

Запуск:

```bash
T_TRADING_TOKEN_SANDBOX=t.xxx pytest tests/e2e/test_sandbox_happy_path.py -v
```

Для прогона нужен **полный sandbox-токен** (с правами OPEN/TRADE) —
read-only не подойдёт. Получить можно в кабинете
https://www.tbank.ru/invest/settings.
"""

from __future__ import annotations

import contextlib
import os
import time
from datetime import date

import pytest

from bond_monitor.domain.shared.money import Lots, PriceUnitPct, Rub
from bond_monitor.domain.portfolio.models import (
    AccountKind,
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.trading.reconciler import reconcile_positions
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

# Маркер для запуска ТОЛЬКО e2e: `pytest -m sandbox`.
pytestmark = pytest.mark.sandbox


_SANDBOX_TOKEN: str = os.getenv("T_TRADING_TOKEN_SANDBOX", "").strip()
_SKIP_REASON = "T_TRADING_TOKEN_SANDBOX не задан — e2e в sandbox пропускается"


def _find_liquid_ofz_figi(token: str) -> tuple[str, PriceUnitPct] | None:
    """Найти первую попавшуюся ликвидную ОФЗ + её последнюю цену в %.

    Возвращает ``(figi, last_price_pct)`` или ``None``, если не нашли —
    тогда тест скипается.

    Идея: ОФЗ всегда есть, торги идут, цена обычно ~85–105%. Берём
    первую, у которой `api_trade_available_flag=True` и есть `last_price`.
    """
    from t_tech.invest import Client, InstrumentStatus
    from t_tech.invest.sandbox.client import SandboxClient

    candidates: list[str] = []
    with SandboxClient(token) as sandbox_client:
        bonds_resp = sandbox_client.instruments.bonds(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
        )
        for bond in bonds_resp.instruments:
            # ОФЗ в Tinkoff API: ISIN с префиксом RU000 и «ОФЗ» в имени.
            if "ОФЗ" not in (bond.name or ""):
                continue
            if not bond.api_trade_available_flag or not bond.buy_available_flag:
                continue
            candidates.append(bond.figi)
            if len(candidates) >= 20:
                break

        for figi in candidates:
            prices_resp = sandbox_client.market_data.get_last_prices(figi=[figi])
            for entry in prices_resp.last_prices:
                p = entry.price
                units = int(getattr(p, "units", 0))
                nano = int(getattr(p, "nano", 0))
                if units == 0 and nano == 0:
                    continue
                price_pct = float(units) + nano / 1_000_000_000.0
                return figi, PriceUnitPct(price_pct)

    # Fallback на production Client — sandbox иногда возвращает пустые
    # last_prices для редких инструментов; в production они есть.
    with Client(token) as client:
        for figi in candidates:
            prices_resp = client.market_data.get_last_prices(figi=[figi])
            for entry in prices_resp.last_prices:
                p = entry.price
                units = int(getattr(p, "units", 0))
                nano = int(getattr(p, "nano", 0))
                if units == 0 and nano == 0:
                    continue
                price_pct = float(units) + nano / 1_000_000_000.0
                return figi, PriceUnitPct(price_pct)
    return None


@pytest.mark.skipif(not _SANDBOX_TOKEN, reason=_SKIP_REASON)
def test_sandbox_happy_path() -> None:
    """Полный цикл sandbox: open → pay_in → BUY → state → snapshot → cancel → close."""
    token = _SANDBOX_TOKEN

    target = _find_liquid_ofz_figi(token)
    if target is None:
        pytest.skip("Не нашли ликвидную ОФЗ для теста (last_prices пусто)")
    figi, last_price_pct = target

    account_id = open_sandbox_account(token, name="bond-monitor-e2e")
    assert account_id, "open_sandbox_account вернул пустой account_id"

    try:
        # ── Аккаунт виден в списке ────────────────────────────────────
        accounts = list_accounts(token, AccountKind.SANDBOX)
        assert any(a.id == account_id for a in accounts), (
            f"Новый sandbox-аккаунт {account_id} не в списке list_accounts"
        )

        # ── Пополнение ────────────────────────────────────────────────
        balance = sandbox_pay_in(token, account_id, Rub(100_000.0))
        assert balance > 0, "sandbox_pay_in вернул нулевой баланс"

        # ── Снимок счёта: должен показывать ~100k RUB и пустые позиции ─
        snapshot_before = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        assert snapshot_before.money_rub > 0
        assert not snapshot_before.bond_positions
        assert not snapshot_before.other_instruments

        # ── BUY 1 лот по цене НИЖЕ рынка (95% от last) — чтобы не сматчилось ─
        buy_price = PriceUnitPct(round(float(last_price_pct) * 0.95, 4))
        request_uid = make_request_uid(
            account_id=account_id,
            figi=figi,
            direction="BUY",
            lots=1,
            pending_op_id="e2e-happy-path",
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
        assert order.order_id, "post_limit_order не вернул order_id"
        assert order.request_uid == request_uid

        # ── State: контракт работает ────────────────────────────────────
        state = get_order_state(
            token,
            AccountKind.SANDBOX,
            account_id=account_id,
            order_id=order.order_id,
        )
        assert state.order_id == order.order_id
        assert state.direction == "BUY"

        # ── Снимок после ордера: money_rub либо уменьшен (если филл),
        # либо заблокирован (часть money_rub в blocked). Главное — структура жива.
        snapshot_after = get_account_snapshot(token, AccountKind.SANDBOX, account_id)
        assert snapshot_after.money_rub >= 0

        # ── Reconcile: проверяем что функция не падает с реальным снапшотом
        portfolio = Portfolio(
            name="E2E test",
            initial_amount_rub=100_000.0,
            horizon_date=date(2027, 1, 1),
            risk_profile=RiskProfile.NORMAL,
        )
        portfolio.mode = PortfolioMode.TRADING
        portfolio.account_id = account_id
        portfolio.account_kind = AccountKind.SANDBOX
        portfolio.positions = [
            PortfolioPosition(
                isin="RU000_E2E",  # plug
                secid="OFZ_E2E",
                name="E2E OFZ",
                lots=1,
                lot_size=10,
                purchase_clean_price_pct=float(buy_price),
                purchase_dirty_price_rub=1000.0,
                purchase_aci_rub=0.0,
                purchase_date=date.today(),
                purchase_amount_rub=1000.0,
                coupon_rate=10.0,
                face_value=1000.0,
                maturity_date=date(2027, 1, 1),
                offer_date=None,
                coupon_period_days=180,
                source=PositionSourceType.INITIAL,
                figi=figi,
            )
        ]
        result = reconcile_positions(portfolio, snapshot_after)
        # Структура drifts валидна (даже если не пуста — это нормально)
        assert isinstance(result.drifts, list)

        # ── Cancel если ещё активна ─────────────────────────────────────
        terminal_statuses = {
            "EXECUTION_REPORT_STATUS_FILL",
            "EXECUTION_REPORT_STATUS_CANCELLED",
            "EXECUTION_REPORT_STATUS_REJECTED",
        }
        # Небольшая пауза: иногда состояние обновляется не мгновенно
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
            assert cancelled, "cancel_order вернул False для активной заявки"
    finally:
        # Гарантированный cleanup даже если ассерт упадёт выше.
        # Sandbox иногда возвращает 5xx при закрытии — глотаем.
        with contextlib.suppress(Exception):
            close_sandbox_account(token, account_id)
