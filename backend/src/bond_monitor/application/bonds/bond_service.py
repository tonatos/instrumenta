"""Bond enrichment and screening pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.policies import DEFAULT_DURATION_POLICY, DurationPolicy, RateScenario
from bond_monitor.domain.screening.scorer import apply_duration_scoring, score_bonds
from bond_monitor.infrastructure.bonds.universe_cache import (
    BondCacheKey,
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
        bonds = score_bonds(bonds, key_rate=self._key_rate, tax_rate=self._tax_rate)
        return bonds, source

    def load_screener_bonds(
        self,
        *,
        filter_by: str = "effective",
        duration_policy: DurationPolicy | None = None,
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
        if (
            policy.rate_scenario != RateScenario.HOLD
            or policy.duration_score_weight > 0
            or policy.target_duration_years is not None
        ):
            bonds = apply_duration_scoring(
                [replace(b) for b in bonds],
                policy,
            )
        return BondLoadResult(bonds=bonds, source=source)

    def load_universe(self) -> BondLoadResult:
        cache_key = self._cache_key("universe")
        cached = get_cached_bonds(cache_key)
        if cached is not None:
            bonds, source = cached
            return BondLoadResult(bonds=bonds, source=source)

        bonds = fetch_all_bonds_unfiltered()
        bonds, source = self._enrich_and_score(bonds)
        put_cached_bonds(cache_key, bonds, source)
        return BondLoadResult(bonds=bonds, source=source)

    def load_by_isins(self, isins: list[str]) -> list[BondRecord]:
        if not isins:
            return []
        bonds = fetch_bonds_by_isins(set(isins))
        bonds, _ = self._enrich_and_score(bonds)
        return bonds

    def load_by_secid(self, secid: str) -> BondRecord | None:
        bond = fetch_bond_by_secid(secid)
        if bond is None:
            return None
        bonds, _ = self._enrich_and_score([bond])
        result = bonds[0] if bonds else None
        if result is not None and self._token:
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
