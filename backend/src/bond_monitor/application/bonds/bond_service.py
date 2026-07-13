"""Bond enrichment and screening pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import RiskProfile
from bond_monitor.domain.portfolio.policies import DEFAULT_DURATION_POLICY, DurationPolicy
from bond_monitor.domain.screening.scorer import (
    score_bonds_all_profiles,
    sort_bonds_by_resolved_score,
)
from bond_monitor.infrastructure.bonds.universe_cache import (
    BondCacheKey,
    clone_bond_record,
    get as get_cached_bonds,
    invalidate_all as invalidate_bond_cache,
    put as put_cached_bonds,
    token_fingerprint,
)
from bond_monitor.infrastructure.moex.client import (
    fetch_all_bonds,
    fetch_all_bonds_unfiltered,
    fetch_bond_by_secid,
    fetch_bonds_by_isins,
    is_moex_cache_fresh,
)
from bond_monitor.infrastructure.moex.defaults_client import enrich_bonds_with_defaults
from bond_monitor.infrastructure.moex.offers_client import enrich_bonds_with_put_offers
from bond_monitor.infrastructure.ratings.loader import (
    apply_ratings,
    load_auto_ratings,
    load_ratings,
    save_auto_ratings,
)
from bond_monitor.infrastructure.ratings.scraper import (
    RatingsScraperError,
    fetch_smartlab_bond_ratings,
)
from bond_monitor.infrastructure.tinvest.read_client import (
    enrich_bond_detail_metadata,
    enrich_bonds_from_tinvest,
    get_bond_coupon_schedule,
)

logger = logging.getLogger(__name__)


@dataclass
class BondLoadResult:
    """Result of bond loading pipeline."""

    bonds: list[BondRecord]
    source: str


class BondService:
    """Application service for bond data loading and enrichment."""

    def __init__(
        self,
        *,
        key_rate: float,
        tax_rate: float,
        tinkoff_token: str = "",
        max_days: int = 120,
        min_volume_rub: float = 500_000,
    ) -> None:
        self._key_rate = key_rate
        self._tax_rate = tax_rate
        self._token = tinkoff_token or None
        self._max_days = max_days
        self._min_volume_rub = min_volume_rub

    def _cache_key(self, kind: str, *, filter_by: str = "") -> BondCacheKey:
        return BondCacheKey(
            key_rate=self._key_rate,
            tax_rate=self._tax_rate,
            token_fingerprint=token_fingerprint(self._token),
            kind=kind,  # type: ignore[arg-type]
            filter_by=filter_by,
            max_days=self._max_days if kind == "screener" else 0,
            min_volume_rub=self._min_volume_rub if kind == "screener" else 0.0,
        )

    def _enrich_and_score(self, bonds: list[BondRecord]) -> tuple[list[BondRecord], str]:
        source = "MOEX ISS API"
        bonds = enrich_bonds_with_defaults(bonds)
        if self._token:
            bonds = enrich_bonds_from_tinvest(bonds, self._token)
            source += " + T-Invest API"
        bonds = enrich_bonds_with_put_offers(bonds)
        ratings = load_ratings()
        auto_ratings = load_auto_ratings()
        bonds = apply_ratings(bonds, ratings, auto_ratings=auto_ratings)
        bonds = score_bonds_all_profiles(bonds, key_rate=self._key_rate, tax_rate=self._tax_rate)
        return bonds, source

    def _score_against_cached_universe(self, bonds: list[BondRecord]) -> list[BondRecord]:
        """Score bonds using YTM scale from the cached full universe."""
        universe_result = self.load_universe()
        by_secid = {b.secid: b for b in universe_result.bonds}
        by_isin = {b.isin: b for b in universe_result.bonds}
        merged = list(universe_result.bonds)
        for bond in bonds:
            if bond.secid not in by_secid and bond.isin not in by_isin:
                merged.append(bond)
        scored_all = score_bonds_all_profiles(
            merged,
            key_rate=self._key_rate,
            tax_rate=self._tax_rate,
        )
        scored_map = {b.secid: b for b in scored_all}
        return [scored_map[bond.secid] for bond in bonds if bond.secid in scored_map]

    def _clone_bonds(self, bonds: list[BondRecord]) -> list[BondRecord]:
        return [clone_bond_record(b) for b in bonds]

    def load_screener_bonds(
        self,
        *,
        filter_by: str = "effective",
        duration_policy: DurationPolicy | None = None,
        risk_profile: RiskProfile = RiskProfile.NORMAL,
    ) -> BondLoadResult:
        cache_key = self._cache_key("screener", filter_by=filter_by)
        cached = get_cached_bonds(cache_key)
        if cached is not None:
            bonds, source = cached
        else:
            bonds = fetch_all_bonds(
                max_days=self._max_days,
                min_volume_rub=self._min_volume_rub,
                filter_by=filter_by,
            )
            bonds, source = self._enrich_and_score(bonds)
            put_cached_bonds(cache_key, bonds, source)

        policy = duration_policy or DEFAULT_DURATION_POLICY
        bonds = self._clone_bonds(bonds)
        bonds = sort_bonds_by_resolved_score(bonds, risk_profile, policy)
        return BondLoadResult(bonds=bonds, source=source)

    def load_universe(self) -> BondLoadResult:
        cache_key = self._cache_key("universe")
        cached = get_cached_bonds(cache_key)
        if cached is not None:
            bonds, source = cached
            return BondLoadResult(bonds=self._clone_bonds(bonds), source=source)

        bonds = fetch_all_bonds_unfiltered()
        bonds, source = self._enrich_and_score(bonds)
        put_cached_bonds(cache_key, bonds, source)
        return BondLoadResult(bonds=self._clone_bonds(bonds), source=source)

    def _lookup_screener_bond(
        self,
        *,
        secid: str | None = None,
        isin: str | None = None,
        filter_by: str = "effective",
        duration_policy: DurationPolicy | None = None,
        risk_profile: RiskProfile = RiskProfile.NORMAL,
    ) -> BondRecord | None:
        result = self.load_screener_bonds(
            filter_by=filter_by,
            duration_policy=duration_policy,
            risk_profile=risk_profile,
        )
        for bond in result.bonds:
            if secid is not None and bond.secid == secid:
                return bond
            if isin is not None and bond.isin == isin:
                return bond
        return None

    def load_by_isins(
        self,
        isins: list[str],
        *,
        filter_by: str = "effective",
        duration_policy: DurationPolicy | None = None,
        risk_profile: RiskProfile = RiskProfile.NORMAL,
    ) -> list[BondRecord]:
        if not isins:
            return []
        policy = duration_policy or DEFAULT_DURATION_POLICY
        found: list[BondRecord] = []
        missing: list[str] = []
        for isin in isins:
            bond = self._lookup_screener_bond(
                isin=isin,
                filter_by=filter_by,
                duration_policy=policy,
                risk_profile=risk_profile,
            )
            if bond is not None:
                found.append(clone_bond_record(bond))
            else:
                missing.append(isin)
        if missing:
            fetched = fetch_bonds_by_isins(set(missing))
            scored = self._score_against_cached_universe(fetched)
            found.extend(scored)
        return found

    def load_by_secid(
        self,
        secid: str,
        *,
        filter_by: str = "effective",
        duration_policy: DurationPolicy | None = None,
        risk_profile: RiskProfile = RiskProfile.NORMAL,
    ) -> BondRecord | None:
        policy = duration_policy or DEFAULT_DURATION_POLICY
        bond = self._lookup_screener_bond(
            secid=secid,
            filter_by=filter_by,
            duration_policy=policy,
            risk_profile=risk_profile,
        )
        if bond is not None:
            result = clone_bond_record(bond)
            if self._token:
                enrich_bond_detail_metadata(result, self._token)
            return result

        bond = fetch_bond_by_secid(secid)
        if bond is None:
            return None
        scored = self._score_against_cached_universe([bond])
        if not scored:
            return None
        result = scored[0]
        if self._token:
            enrich_bond_detail_metadata(result, self._token)
        return result

    def get_coupon_schedule(self, figi: str) -> list[dict]:
        if not self._token or not figi:
            return []
        payments = get_bond_coupon_schedule(self._token, figi)
        return [
            {
                "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                "amount_rub": p.amount_rub,
                "coupon_type_raw": p.coupon_type_raw,
            }
            for p in payments
        ]

    def is_cache_fresh(self) -> bool:
        return is_moex_cache_fresh()

    def refresh_ratings(self) -> int:
        try:
            ratings = fetch_smartlab_bond_ratings()
            save_auto_ratings(ratings)
            return len(ratings)
        except RatingsScraperError as exc:
            logger.error("Ratings refresh failed: %s", exc)
            raise


def invalidate_all_bond_caches() -> None:
    """Clear shared enriched-universe RAM cache (MOEX/T-Invest disk caches are separate)."""
    invalidate_bond_cache()
