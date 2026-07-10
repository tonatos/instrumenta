"""Issuer risk escalation monitoring for held positions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from bond_monitor.domain.bonds.models import RATING_ORDER, BondRecord
from bond_monitor.domain.portfolio.policies import DEFAULT_RISK_MONITOR_POLICY, RiskMonitorPolicy

RiskUrgency = Literal["soon", "critical"]
EscalationKind = Literal[
    "default",
    "technical_default",
    "distress_rating",
    "ig_exit",
    "major_downgrade",
]


@dataclass(frozen=True)
class RiskSnapshot:
    """Minimal risk state for baseline comparison."""

    has_default: bool = False
    has_technical_default: bool = False
    credit_rating: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_default": self.has_default,
            "has_technical_default": self.has_technical_default,
            "credit_rating": self.credit_rating,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskSnapshot:
        return cls(
            has_default=bool(data.get("has_default", False)),
            has_technical_default=bool(data.get("has_technical_default", False)),
            credit_rating=(
                str(data["credit_rating"]) if data.get("credit_rating") is not None else None
            ),
        )


@dataclass(frozen=True)
class RiskEscalation:
    """Detected deterioration vs baseline."""

    kind: EscalationKind
    urgency: RiskUrgency
    reason: str


def risk_snapshot_from_bond(bond: BondRecord) -> RiskSnapshot:
    return RiskSnapshot(
        has_default=bond.has_default,
        has_technical_default=bond.has_technical_default,
        credit_rating=bond.credit_rating,
    )


def _rating_ordinal(rating: str | None) -> int | None:
    if rating is None:
        return None
    return RATING_ORDER.get(rating)


def detect_risk_escalations(
    baseline: RiskSnapshot,
    current: RiskSnapshot,
    *,
    policy: RiskMonitorPolicy = DEFAULT_RISK_MONITOR_POLICY,
) -> list[RiskEscalation]:
    """Return significant risk deteriorations since baseline."""
    events: list[RiskEscalation] = []

    if not baseline.has_default and current.has_default:
        events.append(
            RiskEscalation(
                kind="default",
                urgency="critical",
                reason="Эмитент в дефолте по данным MOEX",
            )
        )

    if not baseline.has_technical_default and current.has_technical_default:
        events.append(
            RiskEscalation(
                kind="technical_default",
                urgency="critical",
                reason="Технический дефолт по данным MOEX",
            )
        )

    base_ord = _rating_ordinal(baseline.credit_rating)
    curr_ord = _rating_ordinal(current.credit_rating)
    if base_ord is not None and curr_ord is not None and curr_ord < base_ord:
        rating_event: RiskEscalation | None = None
        if curr_ord <= policy.distress_rating_ordinal_max:
            rating_event = RiskEscalation(
                kind="distress_rating",
                urgency="critical",
                reason=(
                    f"Кредитный рейтинг снизился до {current.credit_rating} "
                    f"(было {baseline.credit_rating})"
                ),
            )
        elif (
            base_ord >= policy.investment_grade_ordinal_min
            and curr_ord < policy.investment_grade_ordinal_min
        ):
            rating_event = RiskEscalation(
                kind="ig_exit",
                urgency="soon",
                reason=(
                    f"Рейтинг вышел из investment grade: {baseline.credit_rating} → "
                    f"{current.credit_rating}"
                ),
            )
        elif base_ord - curr_ord >= policy.major_downgrade_steps:
            rating_event = RiskEscalation(
                kind="major_downgrade",
                urgency="soon",
                reason=(
                    f"Кредитный рейтинг существенно снижен: {baseline.credit_rating} → "
                    f"{current.credit_rating}"
                ),
            )
        if rating_event is not None:
            events.append(rating_event)

    return events


def sync_risk_baselines(
    baselines: dict[str, RiskSnapshot],
    *,
    holding_isins: set[str],
    universe_by_isin: dict[str, BondRecord],
) -> bool:
    """Capture baselines for new holdings and drop sold ones. Returns True if mutated."""
    changed = False

    for isin in list(baselines):
        if isin not in holding_isins:
            del baselines[isin]
            changed = True

    for isin in holding_isins:
        if isin in baselines:
            continue
        bond = universe_by_isin.get(isin)
        if bond is None:
            continue
        baselines[isin] = risk_snapshot_from_bond(bond)
        changed = True

    return changed


def acknowledge_risk_baseline(
    baselines: dict[str, RiskSnapshot],
    isin: str,
    bond: BondRecord,
) -> bool:
    """Update baseline to current bond risk state."""
    baselines[isin] = risk_snapshot_from_bond(bond)
    return True
