"""
Тесты идемпотентности `make_request_uid` — критично для дедупликации
заявок при повторных кликах.
"""

from __future__ import annotations

from bond_monitor.infrastructure.tinvest.trading_client import make_request_uid


def test_request_uid_deterministic() -> None:
    """Один и тот же набор параметров даёт один и тот же UID."""
    uid1 = make_request_uid(
        account_id="acc-123",
        figi="BBG000ABCDE",
        direction="BUY",
        lots=2,
        order_key="suggestion-456",
    )
    uid2 = make_request_uid(
        account_id="acc-123",
        figi="BBG000ABCDE",
        direction="BUY",
        lots=2,
        order_key="suggestion-456",
    )
    assert uid1 == uid2


def test_request_uid_different_order_key() -> None:
    """Разный `order_key` → разный UID."""
    uid1 = make_request_uid(
        account_id="acc-123",
        figi="BBG000ABCDE",
        direction="BUY",
        lots=2,
        order_key="suggestion-1",
    )
    uid2 = make_request_uid(
        account_id="acc-123",
        figi="BBG000ABCDE",
        direction="BUY",
        lots=2,
        order_key="suggestion-2",
    )
    assert uid1 != uid2


def test_request_uid_different_direction() -> None:
    uid_buy = make_request_uid(
        account_id="acc",
        figi="FIGI",
        direction="BUY",
        lots=1,
        order_key="key",
    )
    uid_sell = make_request_uid(
        account_id="acc",
        figi="FIGI",
        direction="SELL",
        lots=1,
        order_key="key",
    )
    assert uid_buy != uid_sell


def test_request_uid_salt_changes_result() -> None:
    uid1 = make_request_uid(
        account_id="acc",
        figi="FIGI",
        direction="BUY",
        lots=1,
        order_key="key",
    )
    uid2 = make_request_uid(
        account_id="acc",
        figi="FIGI",
        direction="BUY",
        lots=1,
        order_key="key",
        salt="retry-1",
    )
    assert uid1 != uid2


def test_request_uid_uuid_format() -> None:
    uid = make_request_uid(
        account_id="acc",
        figi="FIGI",
        direction="BUY",
        lots=1,
        order_key="key",
    )
    parts = uid.split("-")
    assert len(parts) == 5
    assert len(uid) == 36
