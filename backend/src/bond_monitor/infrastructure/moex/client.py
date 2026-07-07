"""
MOEX ISS API client for bond data.

Reference: https://iss.moex.com/iss/reference/
Endpoint: /engines/stock/markets/bonds/securities.json

Important behaviour:
    The global bond market endpoint returns ALL currently listed bonds in a
    single response (≈3 000–3 500 rows), regardless of the `start` parameter.
    Do NOT use a pagination loop here — the `start` offset is ignored by ISS
    for this endpoint, and a loop would result in the same rows being fetched
    indefinitely until the process is killed.

Performance:
    Raw merged rows are disk-cached (pickle) for CACHE_TTL_SECONDS so that
    Streamlit RAM-cache invalidations and container restarts do not require a
    full network round-trip when the data is still fresh.
"""

from __future__ import annotations

import logging
import pickle
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from bond_monitor.domain.bonds.models import BondRecord, CouponType
from bond_monitor.infrastructure.paths import get_cache_dir

logger = logging.getLogger(__name__)

MOEX_ISS_BASE = "https://iss.moex.com/iss"

# Disk cache — survives container restarts
CACHE_TTL_SECONDS: int = 900  # 15 min — matches MOEX data delay
_CACHE_DIR: Path = get_cache_dir()
_CACHE_FILE: Path = _CACHE_DIR / "moex_bonds.pkl"

_SECURITIES_COLUMNS = ",".join(
    [
        "SECID",
        "BOARDID",
        "SHORTNAME",
        "ISIN",
        "MATDATE",
        "OFFERDATE",
        "PREVDATE",
        "COUPONPERCENT",
        "ACCRUEDINT",
        "FACEVALUE",
        "FACEUNIT",
        "COUPONPERIOD",
        "COUPONVALUE",
        "NEXTCOUPON",
        "LOTSIZE",
        "LOTVALUE",
    ]
)

_MARKETDATA_COLUMNS = ",".join(
    [
        "SECID",
        "BOARDID",
        "LAST",
        "PREVPRICE",
        "YIELDATWAP",
        "YIELD",
        "YIELDCLOSE",
        "DURATION",
        "VALTODAY",
    ]
)

_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)


# ──────────────────────────────────────────────────────────────────────────────
#  Parsing helpers
# ──────────────────────────────────────────────────────────────────────────────


def _parse_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert ISS response block {columns, data} to list of dicts."""
    columns: list[str] = block["columns"]
    return [dict(zip(columns, row, strict=False)) for row in block["data"]]


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str) or value.startswith("0000"):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_ytm(*candidates: Any) -> float | None:
    """Return first non-None non-zero yield candidate."""
    for c in candidates:
        v = _parse_float(c)
        if v is not None and v > 0:
            return v
    return None


# ──────────────────────────────────────────────────────────────────────────────
#  Network fetching
# ──────────────────────────────────────────────────────────────────────────────


def _fetch_from_moex() -> dict[str, dict[str, Any]]:
    """
    Fetch all currently listed bonds from MOEX ISS in a single HTTP request.

    The endpoint returns the complete dataset at once (~3 000–3 500 rows).
    After merging securities with marketdata, the result is deduplicated
    by ISIN keeping the listing with the highest daily volume.
    """
    url = f"{MOEX_ISS_BASE}/engines/stock/markets/bonds/securities.json"
    params = {
        "iss.meta": "off",
        "securities.columns": _SECURITIES_COLUMNS,
        "marketdata.columns": _MARKETDATA_COLUMNS,
    }

    with httpx.Client(
        transport=httpx.HTTPTransport(retries=3),
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as session:
        resp = session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    secs = _parse_block(data["securities"])
    mdata = _parse_block(data["marketdata"])
    logger.info("MOEX ISS: received %d securities rows", len(secs))

    return _merge_rows(secs, mdata)


# ──────────────────────────────────────────────────────────────────────────────
#  Merge / deduplication
# ──────────────────────────────────────────────────────────────────────────────


def _merge_rows(
    all_secs: list[dict[str, Any]],
    all_mdata: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Merge securities + marketdata by (SECID, BOARDID), then deduplicate by ISIN
    keeping the board with the highest VALTODAY (most liquid listing).
    """
    mdata_index: dict[tuple[str, str], dict[str, Any]] = {
        (r["SECID"], r["BOARDID"]): r for r in all_mdata
    }

    by_isin: dict[str, dict[str, Any]] = {}
    for sec in all_secs:
        isin: str = sec.get("ISIN") or ""
        if not isin:
            continue
        key = (sec["SECID"], sec["BOARDID"])
        mdata = mdata_index.get(key, {})
        merged = {**sec, **mdata}

        val_today = _parse_float(merged.get("VALTODAY")) or 0.0
        prev_val = _parse_float(by_isin.get(isin, {}).get("VALTODAY")) or 0.0
        if val_today >= prev_val:
            by_isin[isin] = merged

    return by_isin


# ──────────────────────────────────────────────────────────────────────────────
#  Disk cache
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class _MoexCacheBundle:
    """On-disk MOEX snapshot with previous-session volumes for liquidity filter."""

    saved_date: date
    bonds: dict[str, dict[str, Any]]
    prev_volumes: dict[str, float]


def _filter_volume_rub(bond: BondRecord) -> float:
    """Volume used for min-liquidity filter and liquidity score."""
    return bond.filter_volume_rub


def _prev_volumes_from_bundle(old: _MoexCacheBundle | None, *, today: date) -> dict[str, float]:
    if old is None:
        return {}
    if old.saved_date < today:
        return {
            isin: _parse_float(row.get("VALTODAY")) or 0.0 for isin, row in old.bonds.items()
        }
    return dict(old.prev_volumes)


def _parse_cache_payload(data: object) -> _MoexCacheBundle | None:
    """Support legacy dict-only pickles and v2 bundle format."""
    if isinstance(data, _MoexCacheBundle):
        return data
    if isinstance(data, dict) and "bonds" in data and "saved_date" in data:
        saved = data["saved_date"]
        saved_date = saved if isinstance(saved, date) else date.fromisoformat(str(saved))
        return _MoexCacheBundle(
            saved_date=saved_date,
            bonds=data["bonds"],
            prev_volumes=dict(data.get("prev_volumes") or {}),
        )
    if isinstance(data, dict) and data:
        first = next(iter(data.values()))
        if isinstance(first, dict) and "SECID" in first:
            return _MoexCacheBundle(
                saved_date=date.today(),
                bonds=data,  # type: ignore[arg-type]
                prev_volumes={},
            )
    return None


def _read_disk_cache_bundle(*, allow_stale: bool = False) -> _MoexCacheBundle | None:
    if not _CACHE_FILE.exists():
        return None
    age = time.time() - _CACHE_FILE.stat().st_mtime
    if not allow_stale and age >= CACHE_TTL_SECONDS:
        return None
    try:
        with _CACHE_FILE.open("rb") as fh:
            payload = pickle.load(fh)  # noqa: S301
        bundle = _parse_cache_payload(payload)
        if bundle is None:
            return None
        if not allow_stale:
            logger.info("Disk cache hit: %d bonds, age=%.0fs", len(bundle.bonds), age)
        return bundle
    except Exception:
        logger.warning("Disk cache read failed", exc_info=True)
        return None


def is_moex_cache_fresh() -> bool:
    """Return True if the disk cache exists and is within CACHE_TTL_SECONDS."""
    if not _CACHE_FILE.exists():
        return False
    return (time.time() - _CACHE_FILE.stat().st_mtime) < CACHE_TTL_SECONDS


def invalidate_moex_cache() -> None:
    """Delete MOEX disk cache to force re-fetch on next request."""
    if _CACHE_FILE.exists():
        _CACHE_FILE.unlink()
        logger.info("MOEX disk cache invalidated")


def _fetch_prev_volumes_from_history(
    merged: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """Cold-start fallback: previous session volumes from MOEX history API."""
    prev_dates = [_parse_date(row.get("PREVDATE")) for row in merged.values()]
    trade_date = next((d for d in prev_dates if d is not None), None)
    if trade_date is None:
        return {}

    secid_to_isin = {row["SECID"]: isin for isin, row in merged.items()}
    by_secid: dict[str, float] = {}
    start = 0
    page_size = 100
    url = f"{MOEX_ISS_BASE}/history/engines/stock/markets/bonds/securities.json"

    with httpx.Client(
        transport=httpx.HTTPTransport(retries=3),
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as session:
        while True:
            params = {
                "iss.meta": "off",
                "history.columns": "SECID,VALUE",
                "date": trade_date.isoformat(),
                "start": start,
                "limit": page_size,
            }
            resp = session.get(url, params=params)
            resp.raise_for_status()
            block = resp.json()["history"]
            rows = _parse_block(block)
            if not rows:
                break
            for row in rows:
                secid = row.get("SECID")
                value = _parse_float(row.get("VALUE"))
                if not secid or value is None:
                    continue
                by_secid[secid] = max(by_secid.get(secid, 0.0), value)
            if len(rows) < page_size:
                break
            start += page_size

    prev_volumes: dict[str, float] = {}
    for secid, value in by_secid.items():
        isin = secid_to_isin.get(secid)
        if isin:
            prev_volumes[isin] = max(prev_volumes.get(isin, 0.0), value)

    logger.info(
        "Loaded %d previous-session volumes from MOEX history (%s)",
        len(prev_volumes),
        trade_date.isoformat(),
    )
    return prev_volumes


def _save_disk_cache(
    merged: dict[str, dict[str, Any]],
    *,
    old_bundle: _MoexCacheBundle | None,
) -> _MoexCacheBundle:
    """Atomically write merged rows and prev-session volumes to disk cache."""
    today = date.today()
    prev_volumes = _prev_volumes_from_bundle(old_bundle, today=today)
    if not prev_volumes:
        prev_volumes = _fetch_prev_volumes_from_history(merged)

    bundle = _MoexCacheBundle(saved_date=today, bonds=merged, prev_volumes=prev_volumes)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _CACHE_FILE.with_suffix(".pkl.tmp")
        with tmp_path.open("wb") as fh:
            pickle.dump(bundle, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(_CACHE_FILE)
        logger.info("Disk cache saved: %d bonds → %s", len(merged), _CACHE_FILE)
    except Exception:
        logger.warning("Disk cache save failed", exc_info=True)
    return bundle


def _load_or_fetch_bundle() -> _MoexCacheBundle:
    """Return merged rows + prev-session volumes, refreshing MOEX data when stale."""
    fresh = _read_disk_cache_bundle(allow_stale=False)
    if fresh is not None:
        return fresh

    stale = _read_disk_cache_bundle(allow_stale=True)
    merged = _fetch_from_moex()
    return _save_disk_cache(merged, old_bundle=stale)


# ──────────────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────────────


def _build_bond_record(
    isin: str,
    raw: dict[str, Any],
    today: date,
    *,
    prev_volume_rub: float | None = None,
) -> BondRecord | None:
    """Construct a ``BondRecord`` from one raw merged MOEX row.

    Returns ``None`` when the row should be skipped entirely (foreign
    currency face value, no future maturity/offer date, …). The
    "would the bond pass the screener window?" question is intentionally
    NOT decided here — callers apply their own date / liquidity filters
    so we can reuse the same construction logic for the favorites tab,
    portfolio tab, etc. where the window doesn't apply.
    """
    if raw.get("FACEUNIT", "SUR") != "SUR":
        return None

    maturity = _parse_date(raw.get("MATDATE"))
    offer = _parse_date(raw.get("OFFERDATE"))

    candidates = [d for d in (maturity, offer) if d is not None and d >= today]
    if not candidates:
        return None
    effective = min(candidates)

    days = (effective - today).days
    if days <= 0:
        return None

    val_today = _parse_float(raw.get("VALTODAY")) or 0.0

    ytm = _pick_ytm(raw.get("YIELDATWAP"), raw.get("YIELD"), raw.get("YIELDCLOSE"))
    last_price = _parse_float(raw.get("LAST")) or _parse_float(raw.get("PREVPRICE"))

    face_value = _parse_float(raw.get("FACEVALUE")) or 1000.0
    # LOTSIZE — количество ценных бумаг в лоте (для ~99.9% облигаций MOEX = 1).
    # Fallback: если LOTSIZE отсутствует, восстанавливаем из LOTVALUE = FACEVALUE × LOTSIZE.
    lot_size_raw = _parse_float(raw.get("LOTSIZE"))
    if lot_size_raw is None or lot_size_raw <= 0:
        lot_value = _parse_float(raw.get("LOTVALUE"))
        lot_size_raw = (lot_value / face_value) if (lot_value and face_value > 0) else 1.0
    lot_size = max(1, int(round(lot_size_raw)))

    return BondRecord(
        secid=raw["SECID"],
        isin=isin,
        name=raw.get("SHORTNAME", ""),
        maturity_date=maturity,
        offer_date=offer,
        effective_date=effective,
        days_to_maturity=days,
        ytm=ytm,
        coupon_rate=_parse_float(raw.get("COUPONPERCENT")),
        accrued_interest=_parse_float(raw.get("ACCRUEDINT")),
        coupon_type=CouponType.UNKNOWN,
        coupon_period_days=int(_parse_float(raw.get("COUPONPERIOD")) or 0) or None,
        coupon_value=_parse_float(raw.get("COUPONVALUE")),
        next_coupon_date=_parse_date(raw.get("NEXTCOUPON")),
        last_price=last_price,
        face_value=face_value,
        lot_size=lot_size,
        duration_days=_parse_float(raw.get("DURATION")),
        volume_rub=val_today,
        prev_volume_rub=prev_volume_rub,
    )


def _load_or_fetch_merged() -> dict[str, dict[str, Any]]:
    """Return merged ISIN-keyed rows, hitting the disk cache when fresh."""
    return _load_or_fetch_bundle().bonds


def fetch_all_bonds(
    max_days: int = 120,
    min_volume_rub: float = 500_000.0,
    filter_by: str = "effective",
) -> list[BondRecord]:
    """
    Fetch and filter bonds from MOEX ISS.

    Pipeline:
    1. Load ISIN-merged rows from disk cache when fresh (≤ CACHE_TTL_SECONDS).
    2. Otherwise perform a single HTTP request to the ISS global bond endpoint
       and update the disk cache.
    3. Apply maturity and liquidity filters and return BondRecord list.

    Args:
        max_days: Maximum days to the chosen cap date.
        min_volume_rub: Minimum previous-session RUB trading volume; illiquid bonds
            excluded. ``BondRecord.volume_rub`` (today) is kept for display only.
        filter_by: Which date the ``max_days`` cap is measured against.
            ``"effective"`` (default) — ``min(maturity_date, offer_date)``,
            matches how MOEX itself reports YTM.
            ``"maturity"`` — only ``maturity_date``; surfaces bonds
            guaranteed to be fully redeemed by the cap even if they
            have an earlier put-offer.

    Returns:
        List of BondRecord filtered by maturity window and liquidity.
    """
    today = date.today()
    cutoff = today + timedelta(days=max_days)

    bundle = _load_or_fetch_bundle()
    merged = bundle.bonds
    logger.info("After ISIN deduplication: %d unique bonds", len(merged))

    bonds: list[BondRecord] = []
    for isin, raw in merged.items():
        bond = _build_bond_record(
            isin,
            raw,
            today,
            prev_volume_rub=bundle.prev_volumes.get(isin),
        )
        if bond is None:
            continue

        # ``effective`` (default) — cap by min(maturity, offer); matches
        # MOEX YTM. ``maturity`` — cap strictly by the maturity date so
        # the user sees only bonds guaranteed to be fully redeemed by
        # the cap, regardless of put-offers along the way.
        if filter_by == "maturity":
            if bond.maturity_date is None or bond.maturity_date > cutoff:
                continue
        else:
            if bond.effective_date is None or bond.effective_date > cutoff:
                continue

        if _filter_volume_rub(bond) < min_volume_rub:
            continue

        bonds.append(bond)

    logger.info(
        "Bonds after filtering (≤%d days, prev vol≥%.0f RUB): %d",
        max_days,
        min_volume_rub,
        len(bonds),
    )
    return bonds


def fetch_all_bonds_unfiltered() -> list[BondRecord]:
    """Return all currently traded bonds without any screener window filters.

    Unlike :func:`fetch_all_bonds`, this function does NOT apply
    ``max_days`` or ``min_volume_rub`` restrictions — it returns every
    bond that is still listed on MOEX and has at least one future
    maturity/offer date. Already-redeemed bonds (``_build_bond_record``
    returns ``None``) are silently skipped.

    Used by the portfolio module so that ``auto_compose`` and
    ``build_plan`` see the full universe, regardless of the screener
    sidebar settings. The portfolio's own horizon already gates the
    maturity window: ``auto_compose`` keeps only bonds whose
    ``maturity_date ≤ horizon_date``, and ``select_replacement`` only
    picks bonds that fit ``[purchase_date + MIN_REPLACEMENT_HORIZON_DAYS,
    horizon_date]``.
    """
    today = date.today()
    bundle = _load_or_fetch_bundle()
    merged = bundle.bonds

    bonds: list[BondRecord] = []
    for isin, raw in merged.items():
        bond = _build_bond_record(
            isin,
            raw,
            today,
            prev_volume_rub=bundle.prev_volumes.get(isin),
        )
        if bond is None:
            continue
        bonds.append(bond)

    logger.info("fetch_all_bonds_unfiltered: %d bonds (no window/liquidity filter)", len(bonds))
    return bonds


def fetch_bond_by_secid(secid: str) -> BondRecord | None:
    """Return a single ``BondRecord`` for the given MOEX SECID, ignoring filters.

    Used by the bond detail page: deep links use ``?bond=<SECID>`` and the
    target bond may legitimately fall outside the screener's window
    (e.g. longer maturity than ``max_days`` or lower daily volume than
    ``min_volume_rub``). The detail page must still open in that case,
    so we look the bond up directly in the MOEX merged dataset.

    The MOEX merged cache is keyed by ISIN, so we do a linear scan over
    rows (~3 000 elements) matching on ``SECID``. That's well under 5 ms
    and the merged dict is already in memory via the disk cache.

    Returns ``None`` when the SECID is unknown to MOEX or the bond has
    no future maturity/offer date (already redeemed).
    """
    if not secid:
        return None

    today = date.today()
    bundle = _load_or_fetch_bundle()
    merged = bundle.bonds

    for isin, raw in merged.items():
        if raw.get("SECID") != secid:
            continue
        return _build_bond_record(
            isin,
            raw,
            today,
            prev_volume_rub=bundle.prev_volumes.get(isin),
        )

    return None


def fetch_bonds_by_isins(isins: set[str]) -> list[BondRecord]:
    """Return ``BondRecord`` for a specific set of ISINs.

    Unlike :func:`fetch_all_bonds`, this function does NOT apply any
    maturity-window or liquidity filters — it only checks that the bond
    is still listed on MOEX (present in the merged dataset) and not yet
    matured. Used by the favorites tab where the user wants to see all
    their pinned bonds regardless of the sidebar filters.

    ISINs that are absent from MOEX (delisted/redeemed/never existed)
    or whose all reference dates lie in the past are silently skipped.
    """
    if not isins:
        return []

    today = date.today()
    bundle = _load_or_fetch_bundle()
    merged = bundle.bonds

    bonds: list[BondRecord] = []
    for isin in isins:
        raw = merged.get(isin)
        if raw is None:
            continue
        bond = _build_bond_record(
            isin,
            raw,
            today,
            prev_volume_rub=bundle.prev_volumes.get(isin),
        )
        if bond is not None:
            bonds.append(bond)

    logger.info(
        "Favorites lookup: requested=%d, returned=%d",
        len(isins),
        len(bonds),
    )
    return bonds
