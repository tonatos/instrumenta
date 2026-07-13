"""Unit tests for deploy session domain."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from bond_monitor.domain.trading.advisory import advise, build_holdings
from bond_monitor.domain.trading.deploy_session import (
    DeploySession,
    DeploySessionItem,
    apply_session_staleness,
    build_deploy_session_plan,
    complete_session_if_no_pending,
    mark_item_placed,
    session_items_to_suggestions,
    sync_session_with_orders,
)
from bond_monitor.domain.trading.ports import BrokerActiveOrder, BrokerBondPosition
from bond_monitor.domain.shared.money import PriceUnitPct, Rub
from bond_monitor.domain.trading.policies import DeploySessionPolicy
from factories import make_account_snapshot, make_bond, make_portfolio


def _make_session_with_buy_items(portfolio_id: str = "p1") -> DeploySession:
    now = datetime.now(UTC)
    return DeploySession(
        id="sess-1",
        portfolio_id=portfolio_id,
        status="active",
        items=[
            DeploySessionItem(
                id="item-1",
                kind="buy",
                isin="RU000A1",
                name="Bond A",
                lots=5,
                figi="FIGI-A",
                suggested_price_pct=100.5,
                estimated_amount_rub=50_000.0,
                reason="buy 1",
            ),
            DeploySessionItem(
                id="item-2",
                kind="buy",
                isin="RU000A2",
                name="Bond B",
                lots=3,
                figi="FIGI-B",
                suggested_price_pct=101.0,
                estimated_amount_rub=30_000.0,
                reason="buy 2",
            ),
        ],
        cash_snapshot_rub=100_000.0,
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )


def test_build_deploy_session_plan_includes_buy_and_reinvest() -> None:
    today = date(2026, 7, 10)
    maturity_soon = today
    buy_bond = make_bond(
        isin="RU000BUY1",
        name="Buy pick",
        figi="FIGI-BUY",
        maturity=date(2027, 6, 1),
        price=98.0,
        volume_rub=5_000_000.0,
    )
    reinvest_source = make_bond(
        isin="RU000SRC1",
        name="Maturing",
        figi="FIGI-SRC",
        maturity=maturity_soon,
        price=100.0,
    )
    replacement = make_bond(
        isin="RU000NEW1",
        name="Replacement",
        figi="FIGI-NEW",
        maturity=date(2027, 9, 1),
        price=99.0,
        volume_rub=5_000_000.0,
    )
    portfolio = make_portfolio(
        initial_amount_rub=200_000.0,
        horizon_date=date(2028, 1, 1),
    )
    portfolio.id = "portfolio-1"
    portfolio.api_trade_only = False
    snapshot = make_account_snapshot(
        80_000.0,
        bond_positions={
            "FIGI-SRC": BrokerBondPosition(
                figi="FIGI-SRC",
                instrument_uid="uid-src",
                ticker="SRC",
                quantity=10,
                lots=10,
                blocked=0,
                current_price_pct=PriceUnitPct(100.0),
                current_nkd_rub=Rub(0.0),
                average_price_pct=PriceUnitPct(100.0),
            )
        },
    )
    holdings = build_holdings(snapshot, [reinvest_source, buy_bond, replacement])
    from bond_monitor.domain.trading.advisory import effective_trading_positions

    positions = effective_trading_positions(
        portfolio,
        snapshot,
        [reinvest_source, buy_bond, replacement],
        purchase_date=today,
    )
    session = build_deploy_session_plan(
        portfolio,
        holdings,
        positions,
        [buy_bond, reinvest_source, replacement],
        available_cash=80_000.0,
        today=today,
        key_rate=16.0,
        tax_rate=0.13,
        now=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
    )
    kinds = {item.kind for item in session.items}
    assert "buy" in kinds
    assert "reinvest" in kinds
    assert session.cash_snapshot_rub == 80_000.0
    assert len(session.items) >= 1
    assert all(item.status == "pending" for item in session.items)


def test_session_items_to_suggestions_only_pending() -> None:
    session = _make_session_with_buy_items()
    session.items[0] = DeploySessionItem(
        **{**session.items[0].__dict__, "status": "placed", "order_id": "ord-1"}
    )
    universe = [
        make_bond(isin="RU000A1", figi="FIGI-A"),
        make_bond(isin="RU000A2", figi="FIGI-B"),
    ]
    suggestions = session_items_to_suggestions(session, universe, kinds={"buy"})
    assert len(suggestions) == 1
    assert suggestions[0].isin == "RU000A2"
    assert suggestions[0].id == "item-2"
    assert suggestions[0].lots == 3


def test_mark_item_placed_preserves_remaining_items() -> None:
    session = _make_session_with_buy_items()
    updated = mark_item_placed(session, "item-1", "order-123")
    pending = [item for item in updated.items if item.status == "pending"]
    assert len(pending) == 1
    assert pending[0].isin == "RU000A2"
    assert pending[0].lots == 3
    placed = next(item for item in updated.items if item.id == "item-1")
    assert placed.status == "placed"
    assert placed.order_id == "order-123"
    assert updated.status == "active"


def test_complete_session_when_all_items_placed() -> None:
    session = _make_session_with_buy_items()
    session = mark_item_placed(session, "item-1", "order-1")
    session = mark_item_placed(session, "item-2", "order-2")
    assert session.status == "completed"
    assert all(item.status == "placed" for item in session.items)


def test_complete_session_if_no_pending_on_all_skipped() -> None:
    session = _make_session_with_buy_items()
    session = replace(
        session,
        items=(
            DeploySessionItem(**{**session.items[0].__dict__, "status": "skipped"}),
            DeploySessionItem(**{**session.items[1].__dict__, "status": "skipped"}),
        ),
    )
    completed = complete_session_if_no_pending(session)
    assert completed.status == "completed"


def test_advise_uses_frozen_session_and_keeps_alerts_live() -> None:
    today = date(2026, 7, 10)
    bond_a = make_bond(isin="RU000A1", figi="FIGI-A", price=100.0, volume_rub=5_000_000.0)
    bond_b = make_bond(isin="RU000A2", figi="FIGI-B", price=100.0, volume_rub=5_000_000.0)
    portfolio = make_portfolio(initial_amount_rub=100_000.0, horizon_date=date(2028, 1, 1))
    portfolio.id = "p-advise"
    snapshot = make_account_snapshot(50_000.0)
    session = _make_session_with_buy_items(portfolio_id=portfolio.id)

    advice_frozen = advise(
        portfolio,
        snapshot,
        [],
        [],
        [bond_a, bond_b],
        key_rate=16.0,
        tax_rate=0.13,
        today=today,
        active_session=session,
    )
    buy_isins = [s.isin for s in advice_frozen.suggestions if s.kind == "buy"]
    assert buy_isins == ["RU000A1", "RU000A2"]
    assert advice_frozen.deploy_session is not None
    assert advice_frozen.deploy_session.id == "sess-1"

    session_after_place = mark_item_placed(session, "item-1", "ord-1")
    advice_partial = advise(
        portfolio,
        snapshot,
        [],
        [],
        [bond_a, bond_b],
        key_rate=16.0,
        tax_rate=0.13,
        today=today,
        active_session=session_after_place,
    )
    buy_isins_partial = [s.isin for s in advice_partial.suggestions if s.kind == "buy"]
    assert buy_isins_partial == ["RU000A2"]
    assert advice_partial.suggestions[0].lots == 3


def test_sync_session_marks_filled_on_terminal_order() -> None:
    session = _make_session_with_buy_items()
    session = mark_item_placed(session, "item-1", "ord-fill")
    orders = [
        BrokerActiveOrder(
            order_id="ord-fill",
            request_uid="uid",
            figi="FIGI-A",
            direction="BUY",
            lots_requested=5,
            lots_executed=5,
            status="EXECUTION_REPORT_STATUS_FILL",
            price_pct=100.5,
            total_order_amount_rub=50_000.0,
            initial_commission_rub=0.0,
        )
    ]
    synced = sync_session_with_orders(session, orders)
    filled = next(item for item in synced.items if item.id == "item-1")
    assert filled.status == "filled"


def test_apply_session_staleness_expires_session() -> None:
    session = _make_session_with_buy_items()
    expired = apply_session_staleness(
        session,
        [make_bond(isin="RU000A1"), make_bond(isin="RU000A2")],
        portfolio=make_portfolio(),
        now=session.expires_at + timedelta(seconds=1),
    )
    assert expired.status == "expired"


def test_apply_session_staleness_marks_item_stale_on_price_drift() -> None:
    session = _make_session_with_buy_items()
    portfolio = make_portfolio()
    bond = make_bond(isin="RU000A1", last_price=120.0)
    policy = DeploySessionPolicy(price_drift_stale_pct=5.0)
    updated = apply_session_staleness(
        session,
        [bond, make_bond(isin="RU000A2", last_price=100.0)],
        portfolio=portfolio,
        policy=policy,
    )
    first = updated.items[0]
    assert first.status == "stale"


def test_apply_session_staleness_marks_overdue_reinvest_stale() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    session = DeploySession(
        id="sess-reinvest",
        portfolio_id="p1",
        status="active",
        items=[
            DeploySessionItem(
                id="item-reinvest",
                kind="reinvest",
                isin="RU000NEW1",
                name="Replacement",
                lots=10,
                figi="FIGI-NEW",
                suggested_price_pct=99.0,
                estimated_amount_rub=100_000.0,
                reason="reinvest",
                due_date=date(2026, 7, 24),
            ),
        ],
        cash_snapshot_rub=0.0,
        created_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=23),
    )
    updated = apply_session_staleness(
        session,
        [make_bond(isin="RU000NEW1", figi="FIGI-NEW", last_price=99.0)],
        portfolio=make_portfolio(),
        now=now,
    )
    assert updated.items[0].status == "stale"
    assert any("погашение источника" in w.lower() for w in updated.warnings)


def test_apply_session_staleness_marks_premature_reinvest_stale() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    session = DeploySession(
        id="sess-reinvest-early",
        portfolio_id="p1",
        status="active",
        items=[
            DeploySessionItem(
                id="item-reinvest",
                kind="reinvest",
                isin="RU000NEW1",
                name="Replacement",
                lots=10,
                figi="FIGI-NEW",
                suggested_price_pct=99.0,
                estimated_amount_rub=100_000.0,
                reason="reinvest",
                due_date=date(2026, 7, 24),
            ),
        ],
        cash_snapshot_rub=0.0,
        created_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=23),
    )
    updated = apply_session_staleness(
        session,
        [make_bond(isin="RU000NEW1", figi="FIGI-NEW", last_price=99.0)],
        portfolio=make_portfolio(),
        now=now,
    )
    assert updated.items[0].status == "stale"
    assert any("доступна с" in w for w in updated.warnings)
