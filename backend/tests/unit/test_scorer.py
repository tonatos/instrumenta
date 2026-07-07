"""Unit tests for bond scoring."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.screening.scorer import calc_ytm_score, score_bonds


def test_calc_ytm_score_higher_for_better_ytm() -> None:
    low = calc_ytm_score(10.0, risk_free_net=12.0, max_spread=8.0)
    high = calc_ytm_score(18.0, risk_free_net=12.0, max_spread=8.0)
    assert high > low


def test_score_bonds_fills_ytm_net() -> None:
    bonds = [
        BondRecord(
            secid="TEST",
            isin="RU000TEST",
            name="Test",
            ytm=16.0,
            risk_level=RiskLevel.LOW,
            volume_rub=1_000_000,
            maturity_date=date(2026, 12, 1),
        )
    ]
    scored = score_bonds(bonds, key_rate=14.5, tax_rate=0.13)
    assert scored[0].ytm_net is not None
    assert scored[0].score is not None
