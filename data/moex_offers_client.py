"""
MOEX ISS put-offer schedule enricher.

The securities snapshot (``OFFERDATE``) gives only the nearest offer
execution date. The submission window and offer price live in the
per-instrument bondization block:

    GET /iss/securities/{SECID}/bondization/offers.json

Fields used:
    offerdate        — execution date (should match ``OFFERDATE``)
    offerdatestart   — first day investors may submit exercise requests
    offerdateend     — last day to submit (often ~2 weeks before execution)
    price            — redemption price as % of face value (often ≠ 100)
    offertype        — «Оферта» = investor put-offer

We only fetch for bonds that already have ``offer_date`` in the MOEX
snapshot (~400 instruments, not the full ≈3 000 universe). Results are
cached on disk for 24 h keyed by ISIN.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from core.bond_model import BondRecord

logger = logging.getLogger(__name__)

MOEX_ISS_BASE = "https://iss.moex.com/iss"
CACHE_TTL_SECONDS: int = 24 * 60 * 60

_DEFAULT_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "cache"
_CACHE_DIR: Path = Path(os.getenv("CACHE_DIR") or _DEFAULT_CACHE_DIR)
_CACHE_FILE: Path = _CACHE_DIR / "moex_put_offers.json"

_MAX_WORKERS: int = 10
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

# MOEX offertype value for investor put-offers (not issuer call-offers).
_PUT_OFFER_TYPE = "Оферта"


@dataclass(frozen=True)
class PutOfferSchedule:
    """Nearest future put-offer schedule for one ISIN."""

    offer_date: date
    submission_start: date | None
    submission_end: date | None
    offer_price_pct: float | None


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


def _load_cache() -> dict[str, dict]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        with _CACHE_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        logger.warning("Put-offers cache unreadable, ignoring", exc_info=True)
        return {}


def _save_cache(data: dict[str, dict]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        tmp.replace(_CACHE_FILE)
    except OSError:
        logger.warning("Put-offers cache save failed", exc_info=True)


def _schedule_to_dict(schedule: PutOfferSchedule) -> dict:
    return {
        "offer_date": schedule.offer_date.isoformat(),
        "submission_start": (
            schedule.submission_start.isoformat() if schedule.submission_start else None
        ),
        "submission_end": (
            schedule.submission_end.isoformat() if schedule.submission_end else None
        ),
        "offer_price_pct": schedule.offer_price_pct,
    }


def _schedule_from_dict(data: dict) -> PutOfferSchedule:
    return PutOfferSchedule(
        offer_date=date.fromisoformat(str(data["offer_date"])),
        submission_start=(
            date.fromisoformat(str(data["submission_start"]))
            if data.get("submission_start")
            else None
        ),
        submission_end=(
            date.fromisoformat(str(data["submission_end"])) if data.get("submission_end") else None
        ),
        offer_price_pct=(
            float(data["offer_price_pct"]) if data.get("offer_price_pct") is not None else None
        ),
    )


def _fetch_put_offer_for_secid(secid: str, today: date) -> PutOfferSchedule | None:
    """Fetch nearest future put-offer for one SECID from MOEX bondization."""
    url = f"{MOEX_ISS_BASE}/securities/{secid}/bondization/offers.json"
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url, params={"iss.meta": "off"})
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        logger.debug("Put-offer fetch failed for %s", secid, exc_info=True)
        return None

    offers_block = payload.get("offers")
    if not offers_block:
        return None
    columns: list[str] = offers_block.get("columns", [])
    rows: list[list[Any]] = offers_block.get("data", [])
    if not columns or not rows:
        return None

    col_idx = {name: i for i, name in enumerate(columns)}
    candidates: list[PutOfferSchedule] = []

    for row in rows:
        offer_type = row[col_idx["offertype"]] if "offertype" in col_idx else None
        if offer_type != _PUT_OFFER_TYPE:
            continue
        face_unit = row[col_idx["faceunit"]] if "faceunit" in col_idx else None
        if face_unit and face_unit != "RUB":
            continue
        offer_dt = _parse_date(row[col_idx["offerdate"]])
        if offer_dt is None or offer_dt < today:
            continue
        candidates.append(
            PutOfferSchedule(
                offer_date=offer_dt,
                submission_start=_parse_date(
                    row[col_idx["offerdatestart"]] if "offerdatestart" in col_idx else None
                ),
                submission_end=_parse_date(
                    row[col_idx["offerdateend"]] if "offerdateend" in col_idx else None
                ),
                offer_price_pct=_parse_float(row[col_idx["price"]] if "price" in col_idx else None),
            )
        )

    if not candidates:
        return None
    return min(candidates, key=lambda s: s.offer_date)


def _load_schedules_for_isins(
    isins: set[str],
    secid_by_isin: dict[str, str],
    today: date,
) -> dict[str, PutOfferSchedule]:
    """Return schedules for requested ISINs, using disk cache where fresh."""
    cache = _load_cache()
    now = time.time()
    result: dict[str, PutOfferSchedule] = {}
    to_fetch: list[tuple[str, str]] = []

    for isin in isins:
        secid = secid_by_isin.get(isin)
        if not secid:
            continue
        entry = cache.get(isin)
        if entry and now - entry.get("_fetched_at", 0) < CACHE_TTL_SECONDS:
            sched_data = entry.get("schedule")
            if sched_data is None:
                continue
            result[isin] = _schedule_from_dict(sched_data)
            continue
        to_fetch.append((isin, secid))

    if to_fetch:
        fetched: dict[str, PutOfferSchedule | None] = {}
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(_fetch_put_offer_for_secid, secid, today): isin
                for isin, secid in to_fetch
            }
            for fut in as_completed(futures):
                isin = futures[fut]
                try:
                    fetched[isin] = fut.result()
                except Exception:
                    logger.debug("Put-offer worker failed for %s", isin, exc_info=True)
                    fetched[isin] = None

        for isin, schedule in fetched.items():
            cache[isin] = {
                "_fetched_at": now,
                "schedule": _schedule_to_dict(schedule) if schedule else None,
            }
            if schedule:
                result[isin] = schedule
        _save_cache(cache)

    return result


def enrich_bonds_with_put_offers(
    bonds: list[BondRecord], *, today: date | None = None
) -> list[BondRecord]:
    """Attach put-offer submission windows and offer prices to bonds.

    Only bonds with a non-null ``offer_date`` in the MOEX snapshot are
    queried — the rest are returned unchanged.
    """
    if not bonds:
        return bonds
    ref_date = today or date.today()

    candidates = [b for b in bonds if b.offer_date is not None and b.offer_date >= ref_date]
    if not candidates:
        return bonds

    isins = {b.isin for b in candidates}
    secid_by_isin = {b.isin: b.secid for b in candidates}
    schedules = _load_schedules_for_isins(isins, secid_by_isin, ref_date)

    for bond in bonds:
        schedule = schedules.get(bond.isin)
        if schedule is None:
            continue
        # Prefer bondization execution date when it matches or replaces snapshot.
        bond.offer_date = schedule.offer_date
        bond.offer_submission_start = schedule.submission_start
        bond.offer_submission_end = schedule.submission_end
        bond.offer_price_pct = schedule.offer_price_pct
        # Recalculate effective_date with enriched offer_date.
        dates = [
            d for d in (bond.maturity_date, bond.offer_date) if d is not None and d >= ref_date
        ]
        if dates:
            bond.effective_date = min(dates)
            bond.days_to_maturity = (bond.effective_date - ref_date).days

    logger.info(
        "Put-offer enrichment: %d bonds queried, %d schedules attached",
        len(candidates),
        len(schedules),
    )
    return bonds
