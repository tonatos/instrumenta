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


def test_portfolio_to_response_counts_positions_and_status() -> None:
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
        ),
        PortfolioPosition(
            isin="RU000PEND",
            secid="PEND",
            name="Pending buy",
            lots=2,
            lot_size=1,
            purchase_clean_price_pct=100.0,
            purchase_dirty_price_rub=1000.0,
            purchase_aci_rub=0.0,
            purchase_date=date(2026, 7, 1),
            purchase_amount_rub=2000.0,
            coupon_rate=10.0,
            face_value=1000.0,
            maturity_date=date(2027, 12, 1),
            offer_date=None,
            coupon_period_days=182,
            source=PositionSourceType.INITIAL,
        ),
    ]

    response = portfolio_to_response(portfolio, today=date(2026, 7, 1))
    assert response.positions_count == 2
    assert response.closed_positions_count == 0
    assert all(p.status == "active" for p in response.data.positions)


def test_portfolio_from_dict_ignores_removed_trading_shadow_fields() -> None:
    """Старый JSON с shadow-полями позиций и trading state загружается без ошибок."""
    portfolio = Portfolio.from_dict(
        {
            "id": "legacy-1",
            "name": "Legacy",
            "initial_amount_rub": 50_000.0,
            "horizon_date": "2028-01-01",
            "risk_profile": "normal",
            "mode": "trading",
            "account_id": "acc-legacy",
            "account_kind": "sandbox",
            "cash_balance_rub": 10_000.0,
            "pending_operations": [{"id": "old-op", "kind": "initial_buy"}],
            "trade_records": [{"id": "old-trade"}],
            "acknowledged_top_ups_rub": 5_000.0,
            "instrument_trade_cache": {"FIGI": {"api_trade_available": True}},
            "positions": [
                {
                    "isin": "RU000LEG",
                    "secid": "LEG",
                    "name": "Legacy",
                    "lots": 1,
                    "lot_size": 1,
                    "purchase_clean_price_pct": 100.0,
                    "purchase_dirty_price_rub": 1000.0,
                    "purchase_aci_rub": 0.0,
                    "purchase_date": "2026-01-01",
                    "purchase_amount_rub": 1000.0,
                    "coupon_rate": 10.0,
                    "face_value": 1000.0,
                    "maturity_date": "2027-01-01",
                    "offer_date": None,
                    "coupon_period_days": 182,
                    "source": "initial",
                    "put_offer_decision": "exercise",
                    "actual_lots": 0,
                    "closed_at": "2026-06-15",
                }
            ],
            "slots": [],
        }
    )
    assert portfolio.name == "Legacy"
    assert portfolio.is_trading
    assert portfolio.account_id == "acc-legacy"
    pos = portfolio.positions[0]
    assert pos.lots == 1
    assert not hasattr(pos, "actual_lots") or getattr(pos, "actual_lots", None) is None
