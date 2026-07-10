"""Unit tests for portfolio alert detection rules."""

from __future__ import annotations

from datetime import date, timedelta

from bond_monitor.domain.bonds.offers import PutOfferDecision
from bond_monitor.domain.notifications.models import AlertKind
from bond_monitor.domain.notifications.rules import collect_alerts
from bond_monitor.domain.portfolio.models import PortfolioPosition, PositionSourceType
from bond_monitor.domain.portfolio.risk_monitor import RiskSnapshot
from bond_monitor.domain.trading.holdings import HoldingView
from factories import make_bond, make_portfolio


def _holding(*, isin: str = "RU000A1", figi: str = "FIGI-1", lots: int = 2) -> HoldingView:
    return HoldingView(
        figi=figi,
        isin=isin,
        name="Hold Bond",
        lots=lots,
        quantity=lots,
        lot_size=1,
        current_price_pct=96.0,
        current_nkd_rub=5.0,
        ytm=17.5,
        maturity_date=date(2027, 6, 1),
        offer_date=None,
        market_value_rub=1920.0,
    )


def _put_position(*, today: date) -> PortfolioPosition:
    offer_date = today + timedelta(days=10)
    return PortfolioPosition(
        isin="RU000PO",
        secid="RU000PO",
        name="Put Offer Bond",
        lots=2,
        lot_size=1,
        purchase_clean_price_pct=99.0,
        purchase_dirty_price_rub=990.0,
        purchase_aci_rub=0.0,
        purchase_date=today - timedelta(days=30),
        purchase_amount_rub=1_980.0,
        coupon_rate=12.0,
        face_value=1000.0,
        maturity_date=today + timedelta(days=500),
        offer_date=offer_date,
        offer_submission_start=today - timedelta(days=5),
        offer_submission_end=offer_date - timedelta(days=1),
        offer_price_pct=100.0,
        coupon_period_days=30,
        source=PositionSourceType.ADOPTED,
        figi="FIGI-PO",
    )


def test_collect_alerts_put_offer_action_when_window_open() -> None:
    today = date(2026, 7, 28)
    portfolio = make_portfolio(portfolio_id="p1")
    position = _put_position(today=today)
    bond = make_bond(
        isin=position.isin,
        name=position.name,
        figi=position.figi,
        maturity=position.maturity_date,
    )
    bond.offer_date = position.offer_date
    bond.offer_submission_start = position.offer_submission_start
    bond.offer_submission_end = position.offer_submission_end
    bond.offer_price_pct = position.offer_price_pct

    alerts = collect_alerts(
        portfolio,
        holdings=[_holding(isin=position.isin, figi=position.figi)],
        positions=[position],
        universe=[bond],
        today=today,
    )
    put_alerts = [a for a in alerts if a.kind == AlertKind.PUT_OFFER_ACTION]
    assert len(put_alerts) == 1
    assert put_alerts[0].isin == position.isin
    assert put_alerts[0].urgency in ("soon", "critical")
    assert put_alerts[0].chat_template


def test_collect_alerts_no_put_offer_when_window_not_open() -> None:
    today = date(2026, 7, 10)
    offer_date = date(2026, 8, 7)
    position = PortfolioPosition(
        isin="RU000A109874",
        secid="RU000A109874",
        name="СамолетP15",
        lots=10,
        lot_size=1,
        purchase_clean_price_pct=99.0,
        purchase_dirty_price_rub=990.0,
        purchase_aci_rub=0.0,
        purchase_date=date(2026, 1, 1),
        purchase_amount_rub=99_000.0,
        coupon_rate=12.0,
        face_value=1000.0,
        maturity_date=date(2027, 7, 30),
        offer_date=offer_date,
        offer_price_pct=100.0,
        coupon_period_days=91,
        source=PositionSourceType.ADOPTED,
        figi="FIGI-SAM",
    )
    bond = make_bond(
        isin=position.isin,
        name=position.name,
        figi=position.figi,
        maturity=position.maturity_date,
    )
    bond.offer_date = offer_date
    bond.offer_price_pct = 100.0
    portfolio = make_portfolio()

    alerts = collect_alerts(
        portfolio,
        holdings=[_holding(isin=position.isin, figi=position.figi, lots=10)],
        positions=[position],
        universe=[bond],
        today=today,
    )
    assert not [a for a in alerts if a.kind == AlertKind.PUT_OFFER_ACTION]
    assert not [a for a in alerts if a.kind == AlertKind.PUT_OFFER_WATCH]


def test_collect_alerts_risk_escalation() -> None:
    portfolio = make_portfolio(portfolio_id="p-risk")
    isin = "RU000RISK"
    portfolio.risk_baselines[isin] = RiskSnapshot(credit_rating="ruBBB-")
    bond = make_bond(isin=isin, name="Risk Bond", figi="FIGI-R", credit_rating="ruBB+")
    holding = _holding(isin=isin, figi="FIGI-R")

    alerts = collect_alerts(
        portfolio,
        holdings=[holding],
        positions=[],
        universe=[bond],
        today=date.today(),
    )
    risk_alerts = [a for a in alerts if a.kind == AlertKind.RISK_ESCALATION]
    assert len(risk_alerts) == 1
    assert risk_alerts[0].urgency == "soon"
    assert risk_alerts[0].risk_acknowledgeable is True
    assert "investment grade" in risk_alerts[0].reason.lower() or "рейтинг" in risk_alerts[0].reason.lower()


def test_collect_alerts_risk_critical_default() -> None:
    portfolio = make_portfolio(portfolio_id="p-def")
    isin = "RU000DEF"
    portfolio.risk_baselines[isin] = RiskSnapshot(credit_rating="ruBBB")
    bond = make_bond(isin=isin, name="Default Bond", figi="FIGI-D", has_default=True)
    holding = _holding(isin=isin, figi="FIGI-D")

    alerts = collect_alerts(
        portfolio,
        holdings=[holding],
        positions=[],
        universe=[bond],
        today=date.today(),
    )
    risk_alerts = [a for a in alerts if a.kind == AlertKind.RISK_ESCALATION]
    assert len(risk_alerts) == 1
    assert risk_alerts[0].urgency == "critical"


def test_collect_alerts_put_offer_skipped_when_hold_decision() -> None:
    today = date(2026, 7, 28)
    position = _put_position(today=today)
    position.put_offer_decision = PutOfferDecision.HOLD
    bond = make_bond(isin=position.isin, figi=position.figi, maturity=position.maturity_date)
    bond.offer_date = position.offer_date
    bond.offer_submission_start = position.offer_submission_start
    bond.offer_submission_end = position.offer_submission_end
    bond.offer_price_pct = position.offer_price_pct

    alerts = collect_alerts(
        make_portfolio(),
        holdings=[_holding(isin=position.isin, figi=position.figi)],
        positions=[position],
        universe=[bond],
        today=today,
    )
    assert not [a for a in alerts if a.kind == AlertKind.PUT_OFFER_ACTION]
