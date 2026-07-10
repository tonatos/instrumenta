"""Dev-only notification overrides for local manual testing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.portfolio.position_factory import sync_put_offer_from_bond
from bond_monitor.domain.portfolio.risk_monitor import RiskSnapshot
from bond_monitor.infrastructure.paths import get_cache_dir
from bond_monitor.interfaces.config import get_settings

logger = logging.getLogger(__name__)

DEV_OVERRIDES_FILENAME = "dev_notification_overrides.json"


@dataclass(frozen=True)
class DevPutOfferOverride:
    offer_date: date
    submission_start: date
    submission_end: date
    offer_price_pct: float


@dataclass(frozen=True)
class DevOverrides:
    portfolio_id: str
    put_offers: dict[str, DevPutOfferOverride]
    risk_baselines: dict[str, RiskSnapshot]
    bond_risk: dict[str, dict[str, Any]]


def get_dev_overrides_path() -> Path:
    return get_cache_dir() / DEV_OVERRIDES_FILENAME


def notifications_dev_enabled() -> bool:
    return get_settings().notifications_dev


def _parse_date(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    return date.fromisoformat(value)


def _risk_snapshot_from_dict(data: dict[str, Any]) -> RiskSnapshot:
    return RiskSnapshot(
        has_default=bool(data.get("has_default", False)),
        has_technical_default=bool(data.get("has_technical_default", False)),
        credit_rating=(
            str(data["credit_rating"]) if data.get("credit_rating") is not None else None
        ),
    )


def load_dev_overrides(
    path: Path | None = None,
    *,
    portfolio_id: str | None = None,
) -> DevOverrides | None:
    overrides_path = path or get_dev_overrides_path()
    if not overrides_path.exists():
        return None
    try:
        with overrides_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        logger.warning("Dev overrides unreadable at %s", overrides_path, exc_info=True)
        return None
    if not isinstance(raw, dict):
        return None

    file_portfolio_id = str(raw.get("portfolio_id", ""))
    if portfolio_id is not None and file_portfolio_id != portfolio_id:
        return None

    put_offers: dict[str, DevPutOfferOverride] = {}
    for isin, entry in (raw.get("put_offers") or {}).items():
        if not isinstance(entry, dict):
            continue
        offer_date = _parse_date(entry.get("offer_date"))
        submission_start = _parse_date(entry.get("submission_start"))
        submission_end = _parse_date(entry.get("submission_end"))
        if offer_date is None or submission_start is None or submission_end is None:
            continue
        put_offers[str(isin)] = DevPutOfferOverride(
            offer_date=offer_date,
            submission_start=submission_start,
            submission_end=submission_end,
            offer_price_pct=float(entry.get("offer_price_pct", 100.0)),
        )

    risk_baselines = {
        str(isin): _risk_snapshot_from_dict(entry)
        for isin, entry in (raw.get("risk_baselines") or {}).items()
        if isinstance(entry, dict)
    }
    bond_risk = {
        str(isin): entry
        for isin, entry in (raw.get("bond_risk") or {}).items()
        if isinstance(entry, dict)
    }

    if not file_portfolio_id:
        return None

    return DevOverrides(
        portfolio_id=file_portfolio_id,
        put_offers=put_offers,
        risk_baselines=risk_baselines,
        bond_risk=bond_risk,
    )


def save_dev_overrides(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def build_put_offer_overrides(
    *,
    portfolio_id: str,
    isin: str,
    today: date | None = None,
) -> dict[str, Any]:
    ref = today or date.today()
    offer_date = ref + timedelta(days=10)
    return {
        "portfolio_id": portfolio_id,
        "put_offers": {
            isin: {
                "offer_date": offer_date.isoformat(),
                "submission_start": (ref - timedelta(days=1)).isoformat(),
                "submission_end": (ref + timedelta(days=7)).isoformat(),
                "offer_price_pct": 100.0,
            }
        },
        "risk_baselines": {},
        "bond_risk": {},
    }


def build_risk_default_overrides(*, portfolio_id: str, isin: str) -> dict[str, Any]:
    return {
        "portfolio_id": portfolio_id,
        "put_offers": {},
        "risk_baselines": {
            isin: {
                "has_default": False,
                "has_technical_default": False,
                "credit_rating": "ruBBB",
            }
        },
        "bond_risk": {
            isin: {
                "has_default": True,
                "has_technical_default": False,
            }
        },
    }


def build_risk_downgrade_overrides(*, portfolio_id: str, isin: str) -> dict[str, Any]:
    return {
        "portfolio_id": portfolio_id,
        "put_offers": {},
        "risk_baselines": {
            isin: {
                "has_default": False,
                "has_technical_default": False,
                "credit_rating": "ruBBB-",
            }
        },
        "bond_risk": {
            isin: {
                "credit_rating": "ruBB+",
            }
        },
    }


def _apply_bond_risk_patch(bond: BondRecord, patch: dict[str, Any]) -> None:
    if "credit_rating" in patch:
        bond.credit_rating = (
            str(patch["credit_rating"]) if patch["credit_rating"] is not None else None
        )
    if "has_default" in patch:
        bond.has_default = bool(patch["has_default"])
    if "has_technical_default" in patch:
        bond.has_technical_default = bool(patch["has_technical_default"])


def _apply_put_offer_patch(bond: BondRecord, schedule: DevPutOfferOverride, ref_date: date) -> None:
    bond.offer_date = schedule.offer_date
    bond.offer_submission_start = schedule.submission_start
    bond.offer_submission_end = schedule.submission_end
    bond.offer_price_pct = schedule.offer_price_pct
    dates = [d for d in (bond.maturity_date, bond.offer_date) if d is not None and d >= ref_date]
    if dates:
        bond.effective_date = min(dates)
        bond.days_to_maturity = (bond.effective_date - ref_date).days


def apply_dev_notification_overrides(
    portfolio: Portfolio,
    universe: list[BondRecord],
    positions: list[PortfolioPosition],
    *,
    portfolio_id: str,
    path: Path | None = None,
    today: date | None = None,
) -> bool:
    """Apply dev overrides when file matches portfolio_id. Returns True if applied."""
    overrides = load_dev_overrides(path, portfolio_id=portfolio_id)
    if overrides is None:
        return False

    ref_date = today or date.today()
    universe_by_isin = {bond.isin: bond for bond in universe}

    for isin, patch in overrides.bond_risk.items():
        bond = universe_by_isin.get(isin)
        if bond is not None:
            _apply_bond_risk_patch(bond, patch)

    for isin, baseline in overrides.risk_baselines.items():
        portfolio.risk_baselines[isin] = baseline

    for isin, schedule in overrides.put_offers.items():
        bond = universe_by_isin.get(isin)
        if bond is None:
            continue
        _apply_put_offer_patch(bond, schedule, ref_date)
        for position in positions:
            if position.isin == isin:
                sync_put_offer_from_bond(position, bond)

    logger.info(
        "Applied dev notification overrides for portfolio %s (%d put, %d risk)",
        portfolio_id,
        len(overrides.put_offers),
        len(overrides.bond_risk),
    )
    return True
