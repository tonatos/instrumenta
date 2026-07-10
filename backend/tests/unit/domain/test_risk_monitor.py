"""Unit tests for issuer risk escalation monitoring."""

from __future__ import annotations

import pytest

from bond_monitor.domain.portfolio.policies import DEFAULT_RISK_MONITOR_POLICY, RiskMonitorPolicy
from bond_monitor.domain.portfolio.risk_monitor import (
    RiskEscalation,
    RiskSnapshot,
    detect_risk_escalations,
    risk_snapshot_from_bond,
    sync_risk_baselines,
)
from factories import make_bond


def _snap(
    *,
    has_default: bool = False,
    has_technical_default: bool = False,
    credit_rating: str | None = "ruBBB",
) -> RiskSnapshot:
    return RiskSnapshot(
        has_default=has_default,
        has_technical_default=has_technical_default,
        credit_rating=credit_rating,
    )


def test_no_escalation_when_already_in_default_at_baseline() -> None:
    baseline = _snap(has_default=True, credit_rating="ruBB")
    current = _snap(has_default=True, credit_rating="ruBB")
    assert detect_risk_escalations(baseline, current) == []


def test_no_escalation_when_already_bb_minus_at_baseline() -> None:
    baseline = _snap(credit_rating="ruBB-")
    current = _snap(credit_rating="ruBB-")
    assert detect_risk_escalations(baseline, current) == []


def test_escalation_on_default() -> None:
    baseline = _snap()
    current = _snap(has_default=True)
    events = detect_risk_escalations(baseline, current)
    assert len(events) == 1
    assert events[0].kind == "default"
    assert events[0].urgency == "critical"


def test_escalation_on_technical_default() -> None:
    baseline = _snap()
    current = _snap(has_technical_default=True)
    events = detect_risk_escalations(baseline, current)
    assert len(events) == 1
    assert events[0].kind == "technical_default"
    assert events[0].urgency == "critical"


def test_escalation_on_ig_exit() -> None:
    baseline = _snap(credit_rating="ruBBB-")
    current = _snap(credit_rating="ruBB+")
    events = detect_risk_escalations(baseline, current)
    assert any(e.kind == "ig_exit" for e in events)
    assert events[0].urgency == "soon"


def test_escalation_on_major_downgrade_three_steps() -> None:
    baseline = _snap(credit_rating="ruA")
    current = _snap(credit_rating="ruBBB")
    events = detect_risk_escalations(baseline, current)
    assert any(e.kind == "major_downgrade" for e in events)


def test_escalation_on_distress_rating() -> None:
    baseline = _snap(credit_rating="ruB")
    current = _snap(credit_rating="ruCCC")
    events = detect_risk_escalations(baseline, current)
    assert any(e.kind == "distress_rating" for e in events)
    assert events[0].urgency == "critical"


def test_no_escalation_on_minor_downgrade_inside_ig() -> None:
    baseline = _snap(credit_rating="ruA")
    current = _snap(credit_rating="ruA-")
    assert detect_risk_escalations(baseline, current) == []


def test_no_escalation_on_two_step_downgrade_inside_ig() -> None:
    baseline = _snap(credit_rating="ruAA-")
    current = _snap(credit_rating="ruA")
    assert detect_risk_escalations(baseline, current) == []


def test_no_escalation_when_rating_appears_from_unrated_baseline() -> None:
    baseline = _snap(credit_rating=None)
    current = _snap(credit_rating="ruBB")
    assert detect_risk_escalations(baseline, current) == []


def test_risk_snapshot_from_bond() -> None:
    bond = make_bond(isin="RU000A1", credit_rating="ruA-")
    bond.has_default = True
    snap = risk_snapshot_from_bond(bond)
    assert snap.has_default is True
    assert snap.credit_rating == "ruA-"


def test_sync_risk_baselines_captures_new_holdings_without_alert() -> None:
    bond = make_bond(isin="RU000A1", credit_rating="ruBB-")
    bond.has_default = True
    baselines: dict[str, RiskSnapshot] = {}
    changed = sync_risk_baselines(baselines, holding_isins={"RU000A1"}, universe_by_isin={bond.isin: bond})
    assert changed is True
    assert baselines["RU000A1"].has_default is True
    assert baselines["RU000A1"].credit_rating == "ruBB-"


def test_sync_risk_baselines_removes_sold_positions() -> None:
    baselines = {"RU000A1": _snap(), "RU000A2": _snap()}
    changed = sync_risk_baselines(baselines, holding_isins={"RU000A1"}, universe_by_isin={})
    assert changed is True
    assert "RU000A2" not in baselines


def test_sync_risk_baselines_no_change_when_stable() -> None:
    baselines = {"RU000A1": _snap()}
    changed = sync_risk_baselines(baselines, holding_isins={"RU000A1"}, universe_by_isin={})
    assert changed is False
