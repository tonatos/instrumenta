"""Тесты сериализации позиций со статусом."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioMode,
    PortfolioPosition,
    PositionSourceType,
    RiskProfile,
)
from bond_monitor.interfaces.schemas.serializers import portfolio_to_response


def test_portfolio_to_response_counts_open_positions_and_status() -> None:
    portfolio = Portfolio(
        name="Test",
        initial_amount_rub=100_000.0,
        horizon_date=date(2028, 1, 1),
        risk_profile=RiskProfile.NORMAL,
    )
    portfolio.mode = PortfolioMode.TRADING
    portfolio.positions = [
        PortfolioPosition(
            isin="RU000OPEN",
            secid="OPEN",
            name="Open",
            lots=5,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 1, 1),
            purchase_amount_rub=5000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2027, 1, 1),
            offer_date=None,
            coupon_period_days=182,
            source=PositionSourceType.INITIAL,
            actual_lots=5,
        ),
        PortfolioPosition(
            isin="RU000CLOSED",
            secid="CLOSED",
            name="Closed",
            lots=3,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2025, 1, 1),
            purchase_amount_rub=3000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2026, 6, 1),
            offer_date=None,
            coupon_period_days=182,
            source=PositionSourceType.INITIAL,
            actual_lots=0,
            closed_at=date(2026, 6, 15),
        ),
    ]

    response = portfolio_to_response(portfolio, today=date(2026, 7, 1))
    assert response.positions_count == 1
    assert response.closed_positions_count == 1
    statuses = {p["isin"]: p["status"] for p in response.data["positions"]}
    assert statuses["RU000OPEN"] == "active"
    assert statuses["RU000CLOSED"] == "closed"
