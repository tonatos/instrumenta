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
    offertype        — «Оферта» on MOEX (both investor puts and issuer calls);
                       past exercised puts may appear as «Оферта (состоялась)»

We only fetch for bonds that already have ``offer_date`` in the MOEX
snapshot (~400 instruments, not the full ≈3 000 universe). Results are
cached on disk for 24 h keyed by ISIN.

Issuer-call detection: nearest future offer without a submission window
and without any historical windowed offers in bondization is treated as
an issuer call (coupon-reset trap), not an investor put.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from bond_monitor.domain.bonds.models import BondRecord

logger = logging.getLogger(__name__)

MOEX_ISS_BASE = "https://iss.moex.com/iss"
CACHE_TTL_SECONDS: int = 24 * 60 * 60

from bond_monitor.infrastructure.paths import get_cache_dir

_CACHE_DIR: Path = get_cache_dir()
_CACHE_FILE: Path = _CACHE_DIR / "moex_put_offers.json"

_MAX_WORKERS: int = 10
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

# Bump when offer-type parsing / issuer-call heuristics change (invalidates disk cache).
_CLASSIFIER_VERSION: int = 2


def _is_moex_offer_row(offer_type: Any) -> bool:
    """True for MOEX offer rows («Оферта», «Оферта (состоялась)», …)."""
    return isinstance(offer_type, str) and offer_type.startswith("Оферта")


@dataclass(frozen=True)
class PutOfferSchedule:
    """Nearest future offer schedule for one ISIN."""

    offer_date: date
    submission_start: date | None
    submission_end: date | None
    offer_price_pct: float | None
    is_issuer_call: bool = False


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


def _row_has_submission_window(
    submission_start: date | None,
    submission_end: date | None,
) -> bool:
    return submission_start is not None or submission_end is not None


def _offer_schedule_from_rows(
    rows: list[list[Any]],
    columns: list[str],
    today: date,
) -> PutOfferSchedule | None:
    """Parse bondization offers block into nearest future schedule."""
    if not columns or not rows:
        return None

    col_idx = {name: i for i, name in enumerate(columns)}
    has_window_history = False
    future_candidates: list[PutOfferSchedule] = []

    for row in rows:
        offer_type = row[col_idx["offertype"]] if "offertype" in col_idx else None
        if not _is_moex_offer_row(offer_type):
            continue
        face_unit = row[col_idx["faceunit"]] if "faceunit" in col_idx else None
        if face_unit and face_unit != "RUB":
            continue

        submission_start = _parse_date(
            row[col_idx["offerdatestart"]] if "offerdatestart" in col_idx else None
        )
        submission_end = _parse_date(
            row[col_idx["offerdateend"]] if "offerdateend" in col_idx else None
        )
        if _row_has_submission_window(submission_start, submission_end):
            has_window_history = True

        offer_dt = _parse_date(row[col_idx["offerdate"]])
        if offer_dt is None or offer_dt < today:
            continue

        future_candidates.append(
            PutOfferSchedule(
                offer_date=offer_dt,
                submission_start=submission_start,
                submission_end=submission_end,
                offer_price_pct=_parse_float(
                    row[col_idx["price"]] if "price" in col_idx else None
                ),
            )
        )

    if not future_candidates:
        return None

    nearest = min(future_candidates, key=lambda s: s.offer_date)
    if _row_has_submission_window(nearest.submission_start, nearest.submission_end):
        return nearest
    if has_window_history:
        return nearest

    return PutOfferSchedule(
        offer_date=nearest.offer_date,
        submission_start=nearest.submission_start,
        submission_end=nearest.submission_end,
        offer_price_pct=nearest.offer_price_pct,
        is_issuer_call=True,
    )


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
        "is_issuer_call": schedule.is_issuer_call,
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
        is_issuer_call=bool(data.get("is_issuer_call", False)),
    )


def _fetch_put_offer_for_secid(secid: str, today: date) -> PutOfferSchedule | None:
    """Fetch nearest future offer for one SECID from MOEX bondization."""
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
    return _offer_schedule_from_rows(rows, columns, today)


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
            # Re-fetch schedules cached before issuer-call detection or classifier bumps.
            if "is_issuer_call" not in sched_data:
                to_fetch.append((isin, secid))
                continue
            if entry.get("_classifier_v", 1) < _CLASSIFIER_VERSION:
                to_fetch.append((isin, secid))
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
                "_classifier_v": _CLASSIFIER_VERSION,
                "schedule": _schedule_to_dict(schedule) if schedule else None,
            }
            if schedule:
                result[isin] = schedule
        _save_cache(cache)

    return result


def _apply_issuer_call_schedule(bond: BondRecord, schedule: PutOfferSchedule, ref_date: date) -> None:
    """Conservative handling: horizon to maturity, no investor put rights."""
    bond.call_date = schedule.offer_date
    bond.offer_date = None
    bond.offer_submission_start = None
    bond.offer_submission_end = None
    bond.offer_price_pct = schedule.offer_price_pct
    if bond.maturity_date is not None and bond.maturity_date >= ref_date:
        bond.effective_date = bond.maturity_date
        bond.days_to_maturity = (bond.maturity_date - ref_date).days


def _apply_put_schedule(bond: BondRecord, schedule: PutOfferSchedule, ref_date: date) -> None:
    bond.offer_date = schedule.offer_date
    bond.offer_submission_start = schedule.submission_start
    bond.offer_submission_end = schedule.submission_end
    bond.offer_price_pct = schedule.offer_price_pct
    dates = [d for d in (bond.maturity_date, bond.offer_date) if d is not None and d >= ref_date]
    if dates:
        bond.effective_date = min(dates)
        bond.days_to_maturity = (bond.effective_date - ref_date).days


def enrich_bonds_with_put_offers(
    bonds: list[BondRecord], *, today: date | None = None
) -> list[BondRecord]:
    """Attach put-offer schedules; issuer calls mapped to ``call_date``.

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

    issuer_calls = 0
    for bond in bonds:
        schedule = schedules.get(bond.isin)
        if schedule is None:
            continue
        if schedule.is_issuer_call:
            _apply_issuer_call_schedule(bond, schedule, ref_date)
            issuer_calls += 1
        else:
            _apply_put_schedule(bond, schedule, ref_date)

    logger.info(
        "Put-offer enrichment: %d bonds queried, %d schedules attached (%d issuer calls)",
        len(candidates),
        len(schedules),
        issuer_calls,
    )
    return bonds
