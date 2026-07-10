"""Unit tests for dev notification overrides."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from bond_monitor.domain.notifications.models import AlertKind
from bond_monitor.domain.notifications.rules import WORKER_ALERT_RULES, collect_alerts
from bond_monitor.domain.portfolio.models import PortfolioPosition, PositionSourceType
from bond_monitor.domain.portfolio.risk_monitor import RiskSnapshot
from bond_monitor.domain.trading.holdings import HoldingView
from bond_monitor.dev.overrides import (
    apply_dev_notification_overrides,
    build_put_offer_overrides,
    build_risk_default_overrides,
    load_dev_overrides,
    save_dev_overrides,
)
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


def _adopted_position(*, isin: str, figi: str, today: date) -> PortfolioPosition:
    return PortfolioPosition(
        isin=isin,
        secid=isin,
        name="Hold Bond",
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
        offer_date=None,
        coupon_period_days=30,
        source=PositionSourceType.ADOPTED,
        figi=figi,
    )


def test_apply_dev_overrides_put_offer_triggers_alert(tmp_path: Path) -> None:
    today = date(2026, 7, 10)
    isin = "RU000PO"
    portfolio = make_portfolio(portfolio_id="p1")
    bond = make_bond(isin=isin, name="Put Bond", figi="FIGI-PO")
    holding = _holding(isin=isin, figi="FIGI-PO")
    position = _adopted_position(isin=isin, figi="FIGI-PO", today=today)

    save_dev_overrides(
        tmp_path / "overrides.json",
        build_put_offer_overrides(portfolio_id="p1", isin=isin, today=today),
    )

    apply_dev_notification_overrides(
        portfolio,
        universe=[bond],
        positions=[position],
        portfolio_id="p1",
        path=tmp_path / "overrides.json",
    )

    alerts = collect_alerts(
        portfolio,
        holdings=[holding],
        positions=[position],
        universe=[bond],
        today=today,
        rules=WORKER_ALERT_RULES,
    )
    put_alerts = [a for a in alerts if a.kind == AlertKind.PUT_OFFER_ACTION]
    assert len(put_alerts) == 1
    assert put_alerts[0].isin == isin


def test_apply_dev_overrides_risk_default_triggers_critical(tmp_path: Path) -> None:
    isin = "RU000DEF"
    portfolio = make_portfolio(portfolio_id="p-def")
    bond = make_bond(isin=isin, name="Default Bond", figi="FIGI-D")
    holding = _holding(isin=isin, figi="FIGI-D")

    save_dev_overrides(
        tmp_path / "overrides.json",
        build_risk_default_overrides(portfolio_id="p-def", isin=isin),
    )

    apply_dev_notification_overrides(
        portfolio,
        universe=[bond],
        positions=[],
        portfolio_id="p-def",
        path=tmp_path / "overrides.json",
    )

    alerts = collect_alerts(
        portfolio,
        holdings=[holding],
        positions=[],
        universe=[bond],
        today=date.today(),
        rules=WORKER_ALERT_RULES,
    )
    risk_alerts = [a for a in alerts if a.kind == AlertKind.RISK_ESCALATION]
    assert len(risk_alerts) == 1
    assert risk_alerts[0].urgency == "critical"


def test_load_dev_overrides_ignores_other_portfolio(tmp_path: Path) -> None:
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps(
            {
                "portfolio_id": "other",
                "put_offers": {},
                "risk_baselines": {},
                "bond_risk": {},
            }
        ),
        encoding="utf-8",
    )
    loaded = load_dev_overrides(path, portfolio_id="p1")
    assert loaded is None


def test_apply_dev_overrides_skips_when_portfolio_mismatch(tmp_path: Path) -> None:
    today = date(2026, 7, 10)
    isin = "RU000PO"
    portfolio = make_portfolio(portfolio_id="p1")
    bond = make_bond(isin=isin, figi="FIGI-PO")
    position = _adopted_position(isin=isin, figi="FIGI-PO", today=today)

    save_dev_overrides(
        tmp_path / "overrides.json",
        build_put_offer_overrides(portfolio_id="other", isin=isin, today=today),
    )

    apply_dev_notification_overrides(
        portfolio,
        universe=[bond],
        positions=[position],
        portfolio_id="p1",
        path=tmp_path / "overrides.json",
    )

    assert bond.offer_date is None
