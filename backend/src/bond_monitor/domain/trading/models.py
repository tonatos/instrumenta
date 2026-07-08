"""Доменные модели режима торговли."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal


class AccountKind(StrEnum):
    """Контур T-Invest API: sandbox (виртуальные деньги) или production."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"


ACCOUNT_KIND_LABELS: dict[AccountKind, str] = {
    AccountKind.SANDBOX: "Песочница",
    AccountKind.PRODUCTION: "Боевой",
}


OrderDirection = Literal["BUY", "SELL"]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class FrozenForecast:
    """Скалярный снимок прогноза доходности в момент перехода в режим торговли."""

    expected_xirr_pct: float | None
    expected_total_net_profit_rub: float
    expected_final_value_rub: float
    frozen_initial_amount_rub: float
    horizon_date: date
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_xirr_pct": self.expected_xirr_pct,
            "expected_total_net_profit_rub": self.expected_total_net_profit_rub,
            "expected_final_value_rub": self.expected_final_value_rub,
            "frozen_initial_amount_rub": self.frozen_initial_amount_rub,
            "horizon_date": self.horizon_date.isoformat(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrozenForecast:
        xirr = data.get("expected_xirr_pct")
        return cls(
            expected_xirr_pct=float(xirr) if xirr is not None else None,
            expected_total_net_profit_rub=float(data.get("expected_total_net_profit_rub", 0.0)),
            expected_final_value_rub=float(data.get("expected_final_value_rub", 0.0)),
            frozen_initial_amount_rub=float(data.get("frozen_initial_amount_rub", 0.0)),
            horizon_date=date.fromisoformat(str(data["horizon_date"])),
            created_at=str(data.get("created_at") or _utc_now_iso()),
        )
