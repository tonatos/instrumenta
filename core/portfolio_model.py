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


class PositionSourceType(StrEnum):
    """Происхождение позиции в портфеле.

    * ``INITIAL`` — куплена на стартовый бюджет при создании портфеля.
    * ``REINVEST_MATURITY`` — куплена за счёт возвращённого номинала
      погашённой ранее бумаги.
    * ``REINVEST_PUT_OFFER`` — куплена за счёт предъявления бумаги к
      пут-оферте (решение пользователя ``EXERCISE``).
    * ``REINVEST_COUPON_CASH`` — куплена за счёт накопленных купонных
      выплат, когда ``cash_balance_rub`` стал ≥ стоимости лота.
    """

    INITIAL = "initial"
    REINVEST_MATURITY = "reinvest_maturity"
    REINVEST_PUT_OFFER = "reinvest_put_offer"
    REINVEST_COUPON_CASH = "reinvest_coupon_cash"


class PutOfferDecision(StrEnum):
    """Решение пользователя по пут-оферте конкретной позиции.

    * ``PENDING`` — решение не принято; UI показывает напоминание, расчёт
      по умолчанию идёт до даты погашения.
    * ``EXERCISE`` — предъявить к выкупу: позиция закрывается в дату
      оферты, освободившиеся деньги переходят в слот реинвестиции.
    * ``HOLD`` — держать дальше: оферта игнорируется, расчёт идёт до
      даты погашения.
    """

    PENDING = "pending"
    EXERCISE = "exercise"
    HOLD = "hold"


class ReinvestmentTriggerReason(StrEnum):
    """Что освободило деньги для реинвестиции."""

    MATURITY = "maturity"
    PUT_OFFER = "put_offer"
    COUPON_CASH = "coupon_cash"


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
    source: PositionSourceType = PositionSourceType.INITIAL
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
            "coupon_period_days": self.coupon_period_days,
            "source": self.source.value,
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
            coupon_period_days=(
                int(data["coupon_period_days"])
                if data.get("coupon_period_days") is not None
                else None
            ),
            source=PositionSourceType(data.get("source", PositionSourceType.INITIAL.value)),
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
    confirmed_isin: str | None = None
    gap_days: int = 2
    source_position_isin: str | None = None

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
            "confirmed_isin": self.confirmed_isin,
            "gap_days": self.gap_days,
            "source_position_isin": self.source_position_isin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReinvestmentSlot:
        return cls(
            trigger_date=date.fromisoformat(str(data["trigger_date"])),
            trigger_reason=ReinvestmentTriggerReason(data["trigger_reason"]),
            expected_cash_rub=float(data["expected_cash_rub"]),
            suggested_isin=(str(data["suggested_isin"]) if data.get("suggested_isin") else None),
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
    id: str = field(default_factory=_new_portfolio_id)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    positions: list[PortfolioPosition] = field(default_factory=list)
    slots: list[ReinvestmentSlot] = field(default_factory=list)
    cash_balance_rub: float = 0.0

    def touch(self) -> None:
        """Обновить ``updated_at`` — вызывать перед каждым ``save_portfolios``."""
        self.updated_at = _utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "initial_amount_rub": self.initial_amount_rub,
            "horizon_date": self.horizon_date.isoformat(),
            "risk_profile": self.risk_profile.value,
            "cash_balance_rub": self.cash_balance_rub,
            "positions": [p.to_dict() for p in self.positions],
            "slots": [s.to_dict() for s in self.slots],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Portfolio:
        return cls(
            id=str(data.get("id") or _new_portfolio_id()),
            name=str(data["name"]),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
            initial_amount_rub=float(data["initial_amount_rub"]),
            horizon_date=date.fromisoformat(str(data["horizon_date"])),
            risk_profile=RiskProfile(data.get("risk_profile", RiskProfile.NORMAL.value)),
            cash_balance_rub=float(data.get("cash_balance_rub", 0.0)),
            positions=[PortfolioPosition.from_dict(p) for p in data.get("positions", [])],
            slots=[ReinvestmentSlot.from_dict(s) for s in data.get("slots", [])],
        )
