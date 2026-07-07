"""Broker I/O facade for trading use cases (single patch point in tests)."""

from __future__ import annotations

from bond_monitor.infrastructure.tinvest.read_client import (
    check_trade_available,
    ensure_order_instrument,
    get_last_price_pct,
    resolve_figi_for_isin,
)
from bond_monitor.infrastructure.tinvest.trading_client import (
    cancel_order,
    close_sandbox_account,
    get_account_operations,
    get_account_snapshot,
    get_active_orders,
    get_order_state,
    list_accounts,
    make_request_uid,
    open_sandbox_account,
    post_limit_order,
    post_market_sell_order,
    preview_order_price,
    sandbox_pay_in,
)

__all__ = [
    "cancel_order",
    "check_trade_available",
    "close_sandbox_account",
    "ensure_order_instrument",
    "get_account_operations",
    "get_account_snapshot",
    "get_active_orders",
    "get_last_price_pct",
    "get_order_state",
    "list_accounts",
    "make_request_uid",
    "open_sandbox_account",
    "post_limit_order",
    "post_market_sell_order",
    "preview_order_price",
    "resolve_figi_for_isin",
    "sandbox_pay_in",
]
