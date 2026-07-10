"""
Доменная модель портфеля.

Слой типов для модуля «Портфель»: облигации, купленные / запланированные к
покупке, накопленный кэш, события реинвестиции и решения по пут-офертам.
Класс :class:`Portfolio` — единственный объект, который сериализуется в
``cache/portfolios.json`` (см. :mod:`data.portfolios`).

Архитектурные правила:

* Здесь только структуры данных и их сериализация. Бизнес-логика подбора
  бумаг, моделирования cashflow и фильтрации по риск-профилю — в
  :mod:`core.portfolio_planner`.
* Никаких импортов из ``streamlit`` / ``pandas`` / ``data.*`` — модуль
  должен оставаться чистым и тестируемым в изоляции.
* Все даты сериализуются через ``date.isoformat()`` и десериализуются
  через ``date.fromisoformat()`` — это даёт стабильные diff-ы JSON-файла.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from bond_monitor.domain.bonds.offers import PutOfferDecision
from bond_monitor.domain.trading.models import (
    AccountKind,
    FrozenForecast,
)


class RiskProfile(StrEnum):
    """Риск-профиль портфеля.

    Определяет, какие бумаги (по уровню риска и кредитному рейтингу) попадают
    в кандидатный пул при автосоставе и подборе замен, а также набор весов
    скоринговой модели в :func:`core.scorer.score_bonds_for_profile`.
    """

    NORMAL = "normal"
    AGGRESSIVE = "aggressive"


RISK_PROFILE_LABELS: dict[RiskProfile, str] = {
    RiskProfile.NORMAL: "Нормальный",
    RiskProfile.AGGRESSIVE: "Агрессивный",
}


class PortfolioMode(StrEnum):
    """Режим работы портфеля.

    * ``SIMULATION`` — чистая симуляция. Состав можно собирать заново,
      удалять/добавлять позиции, менять параметры. Прогноз пересчитывается
      каждый рендер. Пут-оферты разруливаются в режиме «лучший исход»
      (см. :func:`core.portfolio_planner.build_plan` с
      ``assume_best_put_outcome=True``).
    * ``TRADING`` — портфель привязан к брокерскому счёту T-Invest,
      состав «заморожен» (нельзя пересоставить, нельзя удалить позицию),
      покупки/продажи делаются заявками с подтверждением пользователя,
      прогноз доходности зафиксирован в :class:`FrozenForecast` на момент
      перехода и не меняется.
    """

    SIMULATION = "simulation"
    TRADING = "trading"


PORTFOLIO_MODE_LABELS: dict[PortfolioMode, str] = {
    PortfolioMode.SIMULATION: "Симуляция",
    PortfolioMode.TRADING: "Торговля",
}


class PositionSourceType(StrEnum):
    """Происхождение позиции в портфеле.

    * ``INITIAL`` — куплена на стартовый бюджет при создании портфеля.
    * ``ADOPTED`` — принята со счёта при sync («реальность определяет»);
      целевые лоты пере-выводятся при каждой синхронизации.
    * ``REINVEST_MATURITY`` — куплена за счёт возвращённого номинала
      погашённой ранее бумаги.
    * ``REINVEST_PUT_OFFER`` — куплена за счёт предъявления бумаги к
      пут-оферте (решение пользователя ``EXERCISE``).
    * ``REINVEST_COUPON_CASH`` — куплена за счёт накопленных купонных
      выплат, когда ``cash_balance_rub`` стал ≥ стоимости лота.
    """

    INITIAL = "initial"
    ADOPTED = "adopted"
    REINVEST_MATURITY = "reinvest_maturity"
    REINVEST_PUT_OFFER = "reinvest_put_offer"
    REINVEST_COUPON_CASH = "reinvest_coupon_cash"


class ReinvestmentTriggerReason(StrEnum):
    """Что освободило деньги для реинвестиции."""

    MATURITY = "maturity"
    PUT_OFFER = "put_offer"
    COUPON_CASH = "coupon_cash"


class ReinvestmentSlotStatus(StrEnum):
    """Статус подбора замены для UI."""

    OK = "ok"
    NO_CANDIDATE = "no_candidate"
    INVALID_SELECTION = "invalid_selection"
    INSUFFICIENT_CASH = "insufficient_cash"


@dataclass
class PortfolioPosition:
    """Одна позиция в портфеле — фактически купленная или запланированная.

    Все поля цен зафиксированы на момент покупки/планирования, чтобы план
    был воспроизводим и не менялся при колебаниях рынка между прогонами.
    Актуальная (live) цена бумаги при необходимости подтягивается из
    универса MOEX отдельно.
    """

    isin: str
    secid: str
    name: str
    lots: int
    lot_size: int
    purchase_clean_price_pct: float
    purchase_dirty_price_rub: float
    purchase_aci_rub: float
    purchase_date: date
    purchase_amount_rub: float
    coupon_rate: float | None
    face_value: float
    maturity_date: date | None
    offer_date: date | None
    coupon_period_days: int | None
    offer_submission_start: date | None = None
    offer_submission_end: date | None = None
    offer_price_pct: float | None = None
    next_coupon_date: date | None = None
    source: PositionSourceType = PositionSourceType.INITIAL
    figi: str | None = None
    put_offer_decision: PutOfferDecision = PutOfferDecision.PENDING

    @property
    def bonds_count(self) -> int:
        """Количество облигаций в позиции (lots * lot_size)."""
        return self.lots * self.lot_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "isin": self.isin,
            "secid": self.secid,
            "name": self.name,
            "lots": self.lots,
            "lot_size": self.lot_size,
            "purchase_clean_price_pct": self.purchase_clean_price_pct,
            "purchase_dirty_price_rub": self.purchase_dirty_price_rub,
            "purchase_aci_rub": self.purchase_aci_rub,
            "purchase_date": self.purchase_date.isoformat(),
            "purchase_amount_rub": self.purchase_amount_rub,
            "coupon_rate": self.coupon_rate,
            "face_value": self.face_value,
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
            "offer_date": self.offer_date.isoformat() if self.offer_date else None,
            "offer_submission_start": (
                self.offer_submission_start.isoformat() if self.offer_submission_start else None
            ),
            "offer_submission_end": (
                self.offer_submission_end.isoformat() if self.offer_submission_end else None
            ),
            "offer_price_pct": self.offer_price_pct,
            "coupon_period_days": self.coupon_period_days,
            "next_coupon_date": (
                self.next_coupon_date.isoformat() if self.next_coupon_date else None
            ),
            "source": self.source.value,
            "figi": self.figi,
            "put_offer_decision": self.put_offer_decision.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortfolioPosition:
        return cls(
            isin=str(data["isin"]),
            secid=str(data["secid"]),
            name=str(data.get("name", "")),
            lots=int(data["lots"]),
            lot_size=int(data["lot_size"]),
            purchase_clean_price_pct=float(data["purchase_clean_price_pct"]),
            purchase_dirty_price_rub=float(data["purchase_dirty_price_rub"]),
            purchase_aci_rub=float(data.get("purchase_aci_rub", 0.0)),
            purchase_date=date.fromisoformat(str(data["purchase_date"])),
            purchase_amount_rub=float(data["purchase_amount_rub"]),
            coupon_rate=(
                float(data["coupon_rate"]) if data.get("coupon_rate") is not None else None
            ),
            face_value=float(data.get("face_value", 1000.0)),
            maturity_date=(
                date.fromisoformat(str(data["maturity_date"]))
                if data.get("maturity_date")
                else None
            ),
            offer_date=(
                date.fromisoformat(str(data["offer_date"])) if data.get("offer_date") else None
            ),
            offer_submission_start=(
                date.fromisoformat(str(data["offer_submission_start"]))
                if data.get("offer_submission_start")
                else None
            ),
            offer_submission_end=(
                date.fromisoformat(str(data["offer_submission_end"]))
                if data.get("offer_submission_end")
                else None
            ),
            offer_price_pct=(
                float(data["offer_price_pct"]) if data.get("offer_price_pct") is not None else None
            ),
            coupon_period_days=(
                int(data["coupon_period_days"])
                if data.get("coupon_period_days") is not None
                else None
            ),
            next_coupon_date=(
                date.fromisoformat(str(data["next_coupon_date"]))
                if data.get("next_coupon_date")
                else None
            ),
            source=PositionSourceType(data.get("source", PositionSourceType.INITIAL.value)),
            figi=(str(data["figi"]) if data.get("figi") else None),
            put_offer_decision=PutOfferDecision(
                data.get("put_offer_decision", PutOfferDecision.PENDING.value)
            ),
        )


@dataclass
class ReinvestmentSlot:
    """Слот будущей реинвестиции в timeline-плане.

    Слот описывает прогнозируемое событие: «в дату ``trigger_date`` ожидается
    приток ``expected_cash_rub``, который предлагается вложить в
    ``suggested_isin`` (можно переназначить через ``confirmed_isin``)».

    ``gap_days`` — количество дней между событием освобождения денег
    (погашение / оферта) и фактической датой покупки замены. Учитывает
    типичный T+1 / T+2 сеттлмент на MOEX.
    """

    trigger_date: date
    trigger_reason: ReinvestmentTriggerReason
    expected_cash_rub: float
    suggested_isin: str | None = None
    suggested_name: str | None = None
    confirmed_isin: str | None = None
    gap_days: int = 2
    source_position_isin: str | None = None
    # Plan-response metadata (not persisted in portfolio JSON).
    status: ReinvestmentSlotStatus = ReinvestmentSlotStatus.OK
    failure_reason: str | None = None
    eligible_candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def selection_mode(self) -> str:
        """``strategy`` — автоподбор; ``manual`` — пользовательский override."""
        return "manual" if self.confirmed_isin else "strategy"

    @property
    def effective_isin(self) -> str | None:
        """ISIN, который реально планируется к покупке (override > suggestion)."""
        return self.confirmed_isin or self.suggested_isin

    @property
    def purchase_date(self) -> date:
        """Дата фактической покупки замены = ``trigger_date + gap_days``."""
        from datetime import timedelta

        return self.trigger_date + timedelta(days=self.gap_days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_date": self.trigger_date.isoformat(),
            "trigger_reason": self.trigger_reason.value,
            "expected_cash_rub": self.expected_cash_rub,
            "suggested_isin": self.suggested_isin,
            "suggested_name": self.suggested_name,
            "confirmed_isin": self.confirmed_isin,
            "gap_days": self.gap_days,
            "source_position_isin": self.source_position_isin,
        }

    def to_plan_dict(self) -> dict[str, Any]:
        """Serialize slot for ``GET /plan`` including UI metadata."""
        data = self.to_dict()
        data["selection_mode"] = self.selection_mode
        data["status"] = self.status.value
        data["failure_reason"] = self.failure_reason
        data["eligible_candidates"] = list(self.eligible_candidates)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReinvestmentSlot:
        return cls(
            trigger_date=date.fromisoformat(str(data["trigger_date"])),
            trigger_reason=ReinvestmentTriggerReason(data["trigger_reason"]),
            expected_cash_rub=float(data["expected_cash_rub"]),
            suggested_isin=(str(data["suggested_isin"]) if data.get("suggested_isin") else None),
            suggested_name=(str(data["suggested_name"]) if data.get("suggested_name") else None),
            confirmed_isin=(str(data["confirmed_isin"]) if data.get("confirmed_isin") else None),
            gap_days=int(data.get("gap_days", 2)),
            source_position_isin=(
                str(data["source_position_isin"]) if data.get("source_position_isin") else None
            ),
        )


def _new_portfolio_id() -> str:
    """UUID4 без дефисов — короткий стабильный идентификатор для JSON."""
    return uuid4().hex


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Portfolio:
    """Полное состояние одного портфеля.

    Хранится в ``cache/portfolios.json`` как часть массива. ``id`` —
    стабильный UUID, не меняется при редактировании; ``name`` —
    отображаемое имя, может повторяться.

    Поля ``positions`` и ``slots`` содержат сохранённое состояние плана
    (явно подтверждённые позиции и пользовательские override-ы по слотам).
    Live-производные данные (текущая стоимость, прогноз cashflow) собираются
    отдельно через :func:`core.portfolio_planner.build_plan`.
    """

    name: str
    initial_amount_rub: float
    horizon_date: date
    risk_profile: RiskProfile
    # Если True (по умолчанию) — в автосборе и реинвесте только бумаги
    # с ``api_trade_available_flag`` из T-Invest (торгуемые через API).
    api_trade_only: bool = True
    # Гардрейл процентного риска: верхний предел средневзв. дюрации корзины (годы).
    max_weighted_duration_years: float | None = None
    # Override целевой дюрации под сценарий по ставке (годы); None — дефолт сценария.
    target_duration_years: float | None = None
    id: str = field(default_factory=_new_portfolio_id)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    positions: list[PortfolioPosition] = field(default_factory=list)
    slots: list[ReinvestmentSlot] = field(default_factory=list)
    cash_balance_rub: float = 0.0
    # ── Поля режима торговли (см. AGENTS.md → «Режим торговли») ──────────
    mode: PortfolioMode = PortfolioMode.SIMULATION
    account_id: str | None = None
    account_kind: AccountKind | None = None
    account_label: str | None = None
    # ISO-таймстамп фиксации режима торговли. Используется как
    # `from_date` для расчёта XIRR и фильтрации операций по портфелю.
    trading_started_at: str | None = None
    frozen_forecast: FrozenForecast | None = None
    # Baseline risk state per ISIN for escalation alerts (trading mode).
    risk_baselines: dict[str, object] = field(default_factory=dict)

    def touch(self) -> None:
        """Обновить ``updated_at`` — вызывать перед каждым ``save_portfolios``."""
        self.updated_at = _utc_now_iso()

    @property
    def is_trading(self) -> bool:
        """``True`` если портфель в режиме торговли."""
        return self.mode == PortfolioMode.TRADING

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "initial_amount_rub": self.initial_amount_rub,
            "horizon_date": self.horizon_date.isoformat(),
            "risk_profile": self.risk_profile.value,
            "api_trade_only": self.api_trade_only,
            "max_weighted_duration_years": self.max_weighted_duration_years,
            "target_duration_years": self.target_duration_years,
            "cash_balance_rub": self.cash_balance_rub,
            "mode": self.mode.value,
            "account_id": self.account_id,
            "account_kind": self.account_kind.value if self.account_kind else None,
            "account_label": self.account_label,
            "trading_started_at": self.trading_started_at,
            "frozen_forecast": (self.frozen_forecast.to_dict() if self.frozen_forecast else None),
            "risk_baselines": {
                isin: (
                    snap.to_dict()
                    if hasattr(snap, "to_dict")
                    else dict(snap)  # type: ignore[arg-type]
                )
                for isin, snap in sorted(self.risk_baselines.items())
            },
            "positions": [p.to_dict() for p in self.positions],
            "slots": [s.to_dict() for s in self.slots],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Portfolio:
        # Миграция: поля режима торговли отсутствуют в JSON старых портфелей,
        # дефолты ставят их в SIMULATION без attach-данных — никаких
        # breaking changes для существующих файлов.
        account_kind_raw = data.get("account_kind")
        frozen_raw = data.get("frozen_forecast")
        from bond_monitor.domain.portfolio.risk_monitor import RiskSnapshot

        risk_baselines_raw = data.get("risk_baselines") or {}
        risk_baselines = {
            str(isin): RiskSnapshot.from_dict(snap)
            for isin, snap in risk_baselines_raw.items()
            if isinstance(snap, dict)
        }
        return cls(
            id=str(data.get("id") or _new_portfolio_id()),
            name=str(data["name"]),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
            initial_amount_rub=float(data["initial_amount_rub"]),
            horizon_date=date.fromisoformat(str(data["horizon_date"])),
            risk_profile=RiskProfile(data.get("risk_profile", RiskProfile.NORMAL.value)),
            api_trade_only=bool(data.get("api_trade_only", True)),
            max_weighted_duration_years=(
                float(data["max_weighted_duration_years"])
                if data.get("max_weighted_duration_years") is not None
                else None
            ),
            target_duration_years=(
                float(data["target_duration_years"])
                if data.get("target_duration_years") is not None
                else None
            ),
            cash_balance_rub=float(data.get("cash_balance_rub", 0.0)),
            mode=PortfolioMode(data.get("mode", PortfolioMode.SIMULATION.value)),
            account_id=(str(data["account_id"]) if data.get("account_id") else None),
            account_kind=(AccountKind(account_kind_raw) if account_kind_raw else None),
            account_label=(str(data["account_label"]) if data.get("account_label") else None),
            trading_started_at=(
                str(data["trading_started_at"]) if data.get("trading_started_at") else None
            ),
            frozen_forecast=(FrozenForecast.from_dict(frozen_raw) if frozen_raw else None),
            risk_baselines=risk_baselines,
            positions=[PortfolioPosition.from_dict(p) for p in data.get("positions", [])],
            slots=[ReinvestmentSlot.from_dict(s) for s in data.get("slots", [])],
        )
