"""Screener score must not accumulate on repeated loads (duration + cache)."""

from __future__ import annotations

from datetime import date

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.domain.bonds.models import BondRecord, RiskLevel
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.portfolio.policies import DurationPolicy, RateScenario, resolve_duration_policy
from bond_monitor.domain.screening.scorer import _duration_scale_years
from bond_monitor.infrastructure.bonds import universe_cache
from bond_monitor.interfaces.schemas.serializers import bond_to_response


def _make_scored_bond(*, secid: str = "LONG") -> BondRecord:
    bond = BondRecord(
        secid=secid,
        isin=f"RU000{secid}",
        name="Long bond",
        ytm=22.0,
        risk_level=RiskLevel.LOW,
        credit_rating="ruA",
        volume_rub=5_000_000,
        maturity_date=date(2028, 12, 1),
        duration_days=730.0,
        profile_scores={"conservative": 70.0, "normal": 72.0, "aggressive": 80.0},
        score=72.0,
        ytm_score=85.0,
        risk_score=75.0,
        liquidity_score=60.0,
    )
    return bond


def setup_function() -> None:
    universe_cache.invalidate_all()
    universe_cache.configure_ttl(60.0)


def test_repeated_load_screener_bonds_does_not_accumulate_duration_score(monkeypatch) -> None:
    bond = _make_scored_bond()
    enrich_calls = {"count": 0}

    def fake_fetch(*_args, **_kwargs):
        return [bond]

    def fake_enrich(self, bonds):
        enrich_calls["count"] += 1
        return bonds, "MOEX ISS API"

    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.fetch_all_bonds",
        fake_fetch,
    )
    monkeypatch.setattr(BondService, "_enrich_and_score", fake_enrich)

    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="")
    policy = resolve_duration_policy(rate_scenario=RateScenario.CUT)

    first = service.load_screener_bonds(duration_policy=policy, risk_profile=RiskProfile.NORMAL)
    second = service.load_screener_bonds(duration_policy=policy, risk_profile=RiskProfile.NORMAL)

    assert enrich_calls["count"] == 1
    scale = _duration_scale_years(first.bonds, policy)
    first_score = bond_to_response(
        first.bonds[0],
        duration_policy=policy,
        duration_scale=scale,
    ).score
    second_score = bond_to_response(
        second.bonds[0],
        duration_policy=policy,
        duration_scale=scale,
    ).score
    assert first_score == second_score
    assert first_score is not None
    assert first_score > 72.0

    cached_bonds, _ = universe_cache.get(
        service._cache_key("screener", filter_by="effective"),
    ) or ([], "")
    assert cached_bonds[0].profile_scores["normal"] == 72.0


def test_profile_scores_dict_not_shared_between_cache_get_and_duration(monkeypatch) -> None:
    bond = _make_scored_bond()
    monkeypatch.setattr(
        "bond_monitor.application.bonds.bond_service.fetch_all_bonds",
        lambda *_a, **_k: [bond],
    )
    monkeypatch.setattr(
        BondService,
        "_enrich_and_score",
        lambda self, bonds: (bonds, "MOEX ISS API"),
    )

    service = BondService(key_rate=14.5, tax_rate=0.13, tinkoff_token="")
    policy = resolve_duration_policy(rate_scenario=RateScenario.CUT)
    service.load_screener_bonds(duration_policy=policy)

    cached_bonds, _ = universe_cache.get(
        service._cache_key("screener", filter_by="effective"),
    ) or ([], "")
    assert cached_bonds[0].profile_scores is not bond.profile_scores
    assert cached_bonds[0].profile_scores["normal"] == 72.0
