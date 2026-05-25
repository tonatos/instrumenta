"""
T-Invest API client for bond enrichment.

Uses the gRPC-based ``t-tech-investments`` Python library
(formerly ``tinkoff-investments``; namespace ``tinkoff`` was renamed to ``t_tech``).

Sources:
  - SDK:  https://opensource.tbank.ru/invest/invest-python
  - Docs: https://developer.tbank.ru/invest/intro/intro

Enrichment adds to existing BondRecord:
  - amortization_flag, floating_coupon_flag, subordinated_flag
  - for_qual_investor_flag, perpetual_flag, call_date
  - risk_level, figi (needed for GetBondCoupons)
  - coupon_type (via GetBondCoupons for floating/variable bonds)

The enrichment is optional: if the token is absent or the API call fails,
the screener still works with reduced risk scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from core.bond_model import BondRecord, CouponType, RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class _TInvestBondData:
    figi: str
    floating_coupon_flag: bool
    amortization_flag: bool
    perpetual_flag: bool
    subordinated_flag: bool
    for_qual_investor_flag: bool
    liquidity_flag: bool
    call_date: date | None
    risk_level: RiskLevel


@dataclass
class CouponPayment:
    payment_date: date | None
    amount_rub: float | None
    coupon_type_raw: int  # raw int from proto CouponType enum


def _ts_to_date(ts: object) -> date | None:
    """Convert proto Timestamp to Python date (UTC). Returns None if zero."""
    if ts is None:
        return None
    seconds: int = getattr(ts, "seconds", 0)
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).date()


def _mv_to_float(mv: object) -> float | None:
    """Convert proto MoneyValue to Python float."""
    if mv is None:
        return None
    units: int = getattr(mv, "units", 0)
    nano: int = getattr(mv, "nano", 0)
    return float(units) + nano / 1_000_000_000.0


def _map_coupon_type(raw: int) -> CouponType:
    """
    Map T-Invest CouponType enum int to our CouponType.

    T-Invest proto values:
      0 = COUPON_TYPE_UNSPECIFIED
      1 = COUPON_TYPE_CONSTANT   (постоянный)
      2 = COUPON_TYPE_FIXED      (фиксированный)
      3 = COUPON_TYPE_FLOATING   (плавающий)
      4 = COUPON_TYPE_OTHER      (иной / переменный)
    """
    if raw in (1, 2):
        return CouponType.FIXED
    if raw == 3:
        return CouponType.FLOATING
    if raw == 4:
        return CouponType.VARIABLE
    return CouponType.UNKNOWN


def _fetch_all_bonds_from_api(token: str) -> dict[str, _TInvestBondData]:
    """
    Call T-Invest GetBonds and return ISIN → _TInvestBondData mapping.
    One API call returns all instruments; no pagination needed.
    """
    try:
        from t_tech.invest import Client, InstrumentStatus
    except ImportError as exc:
        raise ImportError(
            "t-tech-investments is not installed. See requirements.txt for the tarball install URL."
        ) from exc

    result: dict[str, _TInvestBondData] = {}
    with Client(token) as client:
        response = client.instruments.bonds(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
        )
        for bond in response.instruments:
            isin: str = bond.isin
            if not isin:
                continue
            risk_level_raw: int = getattr(bond, "risk_level", 0)
            try:
                risk_level = RiskLevel(min(3, max(0, risk_level_raw)))
            except ValueError:
                risk_level = RiskLevel.UNKNOWN

            result[isin] = _TInvestBondData(
                figi=bond.figi,
                floating_coupon_flag=bond.floating_coupon_flag,
                amortization_flag=bond.amortization_flag,
                perpetual_flag=bond.perpetual_flag,
                subordinated_flag=bond.subordinated_flag,
                for_qual_investor_flag=bond.for_qual_investor_flag,
                liquidity_flag=getattr(bond, "liquidity_flag", True),
                call_date=_ts_to_date(getattr(bond, "call_date", None)),
                risk_level=risk_level,
            )

    logger.info("T-Invest: loaded %d bonds from API", len(result))
    return result


def enrich_bonds_from_tinvest(bonds: list[BondRecord], token: str) -> list[BondRecord]:
    """
    Enrich BondRecord list with flags and risk data from T-Invest API.

    Bonds not found in T-Invest (e.g. delisted or OTC) are left unchanged.
    Any API error is logged and the function returns the unenriched list.
    """
    try:
        {b.isin for b in bonds}
        api_data = _fetch_all_bonds_from_api(token)
    except Exception:
        logger.exception("T-Invest enrichment failed; proceeding without enrichment")
        return bonds

    matched = 0
    for bond in bonds:
        data = api_data.get(bond.isin)
        if data is None:
            continue
        matched += 1
        bond.figi = data.figi
        bond.floating_coupon_flag = data.floating_coupon_flag
        bond.amortization_flag = data.amortization_flag
        bond.perpetual_flag = data.perpetual_flag
        bond.subordinated_flag = data.subordinated_flag
        bond.for_qual_investor_flag = data.for_qual_investor_flag
        bond.liquidity_flag = data.liquidity_flag
        bond.call_date = data.call_date
        bond.risk_level = data.risk_level
        bond.tinvest_enriched = True

        # Derive coupon type from floating flag if not yet set
        if bond.coupon_type == CouponType.UNKNOWN:
            bond.coupon_type = (
                CouponType.FLOATING if data.floating_coupon_flag else CouponType.FIXED
            )

    logger.info(
        "T-Invest enrichment: %d/%d bonds matched (unmatched: %d)",
        matched,
        len(bonds),
        len(bonds) - matched,
    )
    return bonds


def get_bond_coupon_schedule(
    token: str,
    figi: str,
    days_ahead: int = 365,
) -> list[CouponPayment]:
    """
    Fetch upcoming coupon payments for a specific bond.

    Args:
        token: T-Invest API token.
        figi: Bond FIGI identifier (obtained after enrichment).
        days_ahead: Number of days into the future to fetch coupons for.

    Returns:
        List of CouponPayment sorted by date.
    """
    if not figi:
        logger.warning("get_bond_coupon_schedule called with empty figi")
        return []

    try:
        from t_tech.invest import Client
    except ImportError:
        logger.error("t-tech-investments is not installed")
        return []

    from_dt = datetime.now(UTC)
    to_dt = from_dt + timedelta(days=days_ahead)

    try:
        with Client(token) as client:
            resp = client.instruments.get_bond_coupons(
                figi=figi,
                from_=from_dt,
                to=to_dt,
            )
            payments: list[CouponPayment] = []
            for event in resp.events:
                payments.append(
                    CouponPayment(
                        payment_date=_ts_to_date(event.coupon_date),
                        amount_rub=_mv_to_float(event.pay_one_bond),
                        coupon_type_raw=event.coupon_type,
                    )
                )
            payments.sort(key=lambda p: p.payment_date or date.max)
            return payments
    except Exception:
        logger.exception("Failed to fetch coupon schedule for figi=%s", figi)
        return []


def resolve_coupon_type_from_schedule(payments: list[CouponPayment]) -> CouponType:
    """Determine the dominant coupon type from a payment schedule."""
    if not payments:
        return CouponType.UNKNOWN
    type_counts: dict[int, int] = {}
    for p in payments:
        type_counts[p.coupon_type_raw] = type_counts.get(p.coupon_type_raw, 0) + 1
    dominant_raw = max(type_counts, key=lambda k: type_counts[k])
    return _map_coupon_type(dominant_raw)
