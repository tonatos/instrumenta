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
        pending_op_id="op-456",
    )
    uid2 = make_request_uid(
        account_id="acc-123",
        figi="BBG000ABCDE",
        direction="BUY",
        lots=2,
        pending_op_id="op-456",
    )
    assert uid1 == uid2


def test_request_uid_different_pending_op() -> None:
    """Разный `pending_op_id` → разный UID."""
    uid1 = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="BUY",
        lots=1,
        pending_op_id="op-1",
    )
    uid2 = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="BUY",
        lots=1,
        pending_op_id="op-2",
    )
    assert uid1 != uid2


def test_request_uid_different_direction() -> None:
    """BUY и SELL c теми же параметрами — разные UID-ы."""
    uid_buy = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="BUY",
        lots=1,
        pending_op_id="op",
    )
    uid_sell = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="SELL",
        lots=1,
        pending_op_id="op",
    )
    assert uid_buy != uid_sell


def test_request_uid_salt_changes_result() -> None:
    """Передача salt позволяет сознательно сгенерировать новый UID
    (используется при повторной отправке после отмены)."""
    uid1 = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="BUY",
        lots=1,
        pending_op_id="op",
    )
    uid2 = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="BUY",
        lots=1,
        pending_op_id="op",
        salt="retry-2",
    )
    assert uid1 != uid2


def test_request_uid_uuid_format() -> None:
    """UID должен быть в UUID-формате 8-4-4-4-12 hex (36 символов)."""
    uid = make_request_uid(
        account_id="acc",
        figi="BBG",
        direction="BUY",
        lots=1,
        pending_op_id="op",
    )
    assert len(uid) == 36
    assert uid.count("-") == 4
    parts = uid.split("-")
    assert len(parts) == 5
    assert [len(p) for p in parts] == [8, 4, 4, 4, 12]
    # Все символы — hex
    for part in parts:
        int(part, 16)
