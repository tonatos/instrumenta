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
import os
import pickle
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from core.bond_model import BondRecord, CouponType

logger = logging.getLogger(__name__)

MOEX_ISS_BASE = "https://iss.moex.com/iss"

# Disk cache — survives container restarts and Streamlit RAM-cache misses
CACHE_TTL_SECONDS: int = 900  # 15 min — matches MOEX data delay
# Default cache dir is ``<repo_root>/cache`` so the path works identically
# inside Docker (``WORKDIR=/app`` ⇒ ``/app/cache``) and on a developer machine
# without requiring ``CACHE_DIR`` to be set explicitly.
_DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "cache"
_CACHE_DIR: Path = Path(os.getenv("CACHE_DIR") or _DEFAULT_CACHE_DIR)
_CACHE_FILE: Path = _CACHE_DIR / "moex_bonds.pkl"

_SECURITIES_COLUMNS = ",".join(
    [
        "SECID",
        "BOARDID",
        "SHORTNAME",
        "ISIN",
        "MATDATE",
        "OFFERDATE",
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


def is_moex_cache_fresh() -> bool:
    """Return True if the disk cache exists and is within CACHE_TTL_SECONDS."""
    if not _CACHE_FILE.exists():
        return False
    return (time.time() - _CACHE_FILE.stat().st_mtime) < CACHE_TTL_SECONDS


def _load_disk_cache() -> dict[str, dict[str, Any]] | None:
    """Return cached ISIN-keyed rows if fresh, else None."""
    if not _CACHE_FILE.exists():
        return None
    age = time.time() - _CACHE_FILE.stat().st_mtime
    if age >= CACHE_TTL_SECONDS:
        logger.debug("Disk cache stale: age=%.0fs >= TTL=%ds", age, CACHE_TTL_SECONDS)
        return None
    try:
        with _CACHE_FILE.open("rb") as fh:
            data: dict[str, dict[str, Any]] = pickle.load(fh)  # noqa: S301
        logger.info("Disk cache hit: %d bonds, age=%.0fs", len(data), age)
        return data
    except Exception:
        logger.warning("Disk cache read failed, will re-fetch", exc_info=True)
        return None


def _save_disk_cache(merged: dict[str, dict[str, Any]]) -> None:
    """Atomically write merged rows to disk cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _CACHE_FILE.with_suffix(".pkl.tmp")
        with tmp_path.open("wb") as fh:
            pickle.dump(merged, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(_CACHE_FILE)
        logger.info("Disk cache saved: %d bonds → %s", len(merged), _CACHE_FILE)
    except Exception:
        logger.warning("Disk cache save failed", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────────────


def _build_bond_record(isin: str, raw: dict[str, Any], today: date) -> BondRecord | None:
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
    )


def _load_or_fetch_merged() -> dict[str, dict[str, Any]]:
    """Return merged ISIN-keyed rows, hitting the disk cache when fresh."""
    merged = _load_disk_cache()
    if merged is None:
        merged = _fetch_from_moex()
        _save_disk_cache(merged)
    return merged


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
        min_volume_rub: Minimum daily RUB trading volume; illiquid bonds excluded.
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

    merged = _load_or_fetch_merged()
    logger.info("After ISIN deduplication: %d unique bonds", len(merged))

    bonds: list[BondRecord] = []
    for isin, raw in merged.items():
        bond = _build_bond_record(isin, raw, today)
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

        if (bond.volume_rub or 0.0) < min_volume_rub:
            continue

        bonds.append(bond)

    logger.info(
        "Bonds after filtering (≤%d days, vol≥%.0f RUB): %d",
        max_days,
        min_volume_rub,
        len(bonds),
    )
    return bonds


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
    merged = _load_or_fetch_merged()

    bonds: list[BondRecord] = []
    for isin in isins:
        raw = merged.get(isin)
        if raw is None:
            continue
        bond = _build_bond_record(isin, raw, today)
        if bond is not None:
            bonds.append(bond)

    logger.info(
        "Favorites lookup: requested=%d, returned=%d",
        len(isins),
        len(bonds),
    )
    return bonds
