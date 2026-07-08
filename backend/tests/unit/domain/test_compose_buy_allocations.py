"""Tests for compose_buy_allocations — unified cash deployment via auto_compose."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.auto_compose import compose_buy_allocations
from bond_monitor.domain.portfolio.plan_models import MAX_AUTO_POSITIONS, MIN_AUTO_POSITIONS
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.trading.models import AccountKind


def _bond(isin: str, *, price: float = 1000.0, ytm: float = 12.0) -> BondRecord:
    bond = BondRecord(
        secid=isin[:6],
        isin=isin,
        name=f"Bond {isin[-3:]}",
        maturity_date=date(2026, 12, 31),
        last_price=100.0,
        face_value=1000.0,
        lot_size=1,
        coupon_rate=10.0,
        coupon_period_days=180,
        volume_rub=1_000_000.0,
        liquidity_flag=True,
        credit_rating="ruAAA",
        risk_level=RiskLevel.LOW,
        ytm=ytm,
        ytm_net=10.0,
    )
    bond.accrued_interest = 0.0
    bond.last_price = price / 10.0
    return bond


def _universe(count: int = 8) -> list[BondRecord]:
    return [_bond(f"RU000A{i:03d}", ytm=12.0 + i) for i in range(count)]


def test_compose_buy_allocations_zero_cash() -> None:
    allocs, notes = compose_buy_allocations(
        total_budget_rub=100_000.0,
        cash_to_deploy_rub=0.0,
        current_lots_by_isin={},
        universe=_universe(),
        profile=RiskProfile.NORMAL,
        horizon_date=date(2026, 12, 31),
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
        api_trade_only=False,
        account_kind=AccountKind.SANDBOX,
    )
    assert not allocs
    assert any("≤ 0" in n for n in notes)


def test_compose_buy_allocations_empty_account_diversifies() -> None:
    cash = 100_000.0
    allocs, _notes = compose_buy_allocations(
        total_budget_rub=cash,
        cash_to_deploy_rub=cash,
        current_lots_by_isin={},
        universe=_universe(),
        profile=RiskProfile.NORMAL,
        horizon_date=date(2026, 12, 31),
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
        api_trade_only=False,
        account_kind=AccountKind.SANDBOX,
    )
    assert len(allocs) >= MIN_AUTO_POSITIONS
    assert len({a.isin for a in allocs}) == len(allocs)
    assert sum(a.estimated_amount_rub for a in allocs) <= cash
    assert max(a.estimated_amount_rub for a in allocs) <= cash * 0.30 + 1


def test_compose_buy_allocations_with_existing_holdings_not_single_bond() -> None:
    universe = _universe()
    cash = 100_000.0
    holdings_value = 50_000.0
    allocs, _notes = compose_buy_allocations(
        total_budget_rub=holdings_value + cash,
        cash_to_deploy_rub=cash,
        current_lots_by_isin={"RU000A000": 50},
        universe=universe,
        profile=RiskProfile.NORMAL,
        horizon_date=date(2026, 12, 31),
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
        api_trade_only=False,
        account_kind=AccountKind.SANDBOX,
    )
    assert allocs
    assert len(allocs) > 1 or len({a.isin for a in allocs}) > 1
    assert sum(a.estimated_amount_rub for a in allocs) <= cash


def _existing_lots(count: int, *, lots: int = 10) -> dict[str, int]:
    return {f"RU000A{i:03d}": lots for i in range(count)}


def test_compose_buy_allocations_caps_new_isins_when_eight_existing() -> None:
    existing = _existing_lots(8)
    cash = 200_000.0
    holdings_value = 8 * 10 * 1_000.0
    allocs, _notes = compose_buy_allocations(
        total_budget_rub=holdings_value + cash,
        cash_to_deploy_rub=cash,
        current_lots_by_isin=existing,
        universe=_universe(15),
        profile=RiskProfile.NORMAL,
        horizon_date=date(2026, 12, 31),
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
        api_trade_only=False,
        account_kind=AccountKind.SANDBOX,
    )
    assert allocs
    new_isins = {a.isin for a in allocs if not a.is_existing_position}
    assert len(new_isins) <= MAX_AUTO_POSITIONS - len(existing)
    assert len(existing) + len(new_isins) <= MAX_AUTO_POSITIONS


def test_compose_buy_allocations_ten_existing_only_topups() -> None:
    existing = _existing_lots(10)
    cash = 100_000.0
    holdings_value = 10 * 10 * 1_000.0
    allocs, _notes = compose_buy_allocations(
        total_budget_rub=holdings_value + cash,
        cash_to_deploy_rub=cash,
        current_lots_by_isin=existing,
        universe=_universe(15),
        profile=RiskProfile.NORMAL,
        horizon_date=date(2026, 12, 31),
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
        api_trade_only=False,
        account_kind=AccountKind.SANDBOX,
    )
    assert allocs
    assert all(a.is_existing_position for a in allocs)
    assert all(a.isin in existing for a in allocs)


def test_compose_buy_allocations_twelve_existing_only_top_ten_scored() -> None:
    existing = _existing_lots(12)
    cash = 500_000.0
    holdings_value = 12 * 10 * 1_000.0
    universe = _universe(15)
    allocs, _notes = compose_buy_allocations(
        total_budget_rub=holdings_value + cash,
        cash_to_deploy_rub=cash,
        current_lots_by_isin=existing,
        universe=universe,
        profile=RiskProfile.NORMAL,
        horizon_date=date(2026, 12, 31),
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
        api_trade_only=False,
        account_kind=AccountKind.SANDBOX,
    )
    assert allocs
    assert all(a.is_existing_position for a in allocs)
    # Низкий YTM у RU000A000 и RU000A001 — вне топ-10 держимых.
    assert "RU000A000" not in {a.isin for a in allocs}
    assert "RU000A001" not in {a.isin for a in allocs}
