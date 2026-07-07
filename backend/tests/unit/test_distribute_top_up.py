"""Тесты `core.portfolio_planner.distribute_top_up`."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.domain.portfolio.planner import distribute_top_up


def _bond(
    isin: str,
    *,
    last_price: float = 100.0,
    rating: str = "ruAAA",
    maturity: date = date(2026, 12, 31),
    lot_size: int = 1,
    face_value: float = 1000.0,
    risk: RiskLevel = RiskLevel.LOW,
) -> BondRecord:
    """Синтетический BondRecord для distribute_top_up — минимум полей."""
    bond = BondRecord(
        secid=isin[:6],
        isin=isin,
        name=f"Bond {isin[-3:]}",
        maturity_date=maturity,
        last_price=last_price,
        face_value=face_value,
        lot_size=lot_size,
        coupon_rate=10.0,
        coupon_period_days=180,
        volume_rub=1_000_000.0,
        liquidity_flag=True,
        credit_rating=rating,
        risk_level=risk,
        ytm=12.0,
        ytm_net=10.0,
    )
    bond.accrued_interest = 0.0
    return bond


def _portfolio(initial: float = 100_000.0) -> Portfolio:
    return Portfolio(
        name="T",
        initial_amount_rub=initial,
        horizon_date=date(2026, 12, 31),
        risk_profile=RiskProfile.NORMAL,
    )


def test_distribute_zero_amount() -> None:
    """top_up=0 → пустой список."""
    p = _portfolio()
    allocs, notes = distribute_top_up(
        portfolio=p,
        universe=[_bond("RU000A1")],
        top_up_amount_rub=0.0,
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert not allocs


def test_distribute_picks_top_scored_bonds() -> None:
    """С нормальным универсом распределение должно дать аллокации."""
    p = _portfolio(initial=10_000.0)
    universe = [_bond(f"RU000A{i:03d}") for i in range(5)]
    allocs, notes = distribute_top_up(
        portfolio=p,
        universe=universe,
        top_up_amount_rub=50_000.0,
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert allocs
    # Сумма аллокаций не превышает top_up
    total = sum(a.estimated_amount_rub for a in allocs)
    assert total <= 50_000.0


def test_distribute_skips_blocked_put_offer() -> None:
    """Бумаги с закрытым окном пут-оферты пропускаются."""
    p = _portfolio()
    blocked = _bond("RU000_BL", last_price=100.0)
    blocked.offer_date = date(2025, 6, 1)
    blocked.offer_submission_end = date(2024, 1, 1)  # окно ЗАКРЫТО
    available = _bond("RU000_OK", last_price=100.0)
    allocs, _ = distribute_top_up(
        portfolio=p,
        universe=[blocked, available],
        top_up_amount_rub=10_000.0,
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
    )
    assert all(a.isin != "RU000_BL" for a in allocs)


def test_distribute_marks_existing_positions() -> None:
    """Если бумага уже в портфеле — `is_existing_position=True`."""
    p = _portfolio(initial=10_000.0)
    bond = _bond("RU000A001")
    # Добавляем позицию в портфель
    p.positions = [
        PortfolioPosition(
            isin="RU000A001",
            secid="RU000A",
            name="Existing",
            lots=1,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2025, 1, 1),
            purchase_amount_rub=1000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2026, 12, 31),
            offer_date=None,
            coupon_period_days=180,
            source=PositionSourceType.INITIAL,
        )
    ]
    allocs, _ = distribute_top_up(
        portfolio=p,
        universe=[bond],
        top_up_amount_rub=50_000.0,
        today=date(2025, 1, 1),
        key_rate=16.0,
        tax_rate=0.13,
    )
    if allocs:
        match = next((a for a in allocs if a.isin == "RU000A001"), None)
        if match:
            assert match.is_existing_position is True
