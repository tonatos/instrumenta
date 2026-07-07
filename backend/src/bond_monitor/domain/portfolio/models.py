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
from typing import Any, Literal
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


class AccountKind(StrEnum):
    """Контур T-Invest API: sandbox (виртуальные деньги) или production.

    Sandbox использует отдельный endpoint и токен (``T_TRADING_TOKEN_SANDBOX``),
    в нём нет реальных корпоративных событий (купоны, оферты не приходят
    автоматически). Production — реальный счёт, реальный токен
    (``T_TRADING_TOKEN_PRODUCTION``), полный обвес проверок и audit-log.
    """

    SANDBOX = "sandbox"
    PRODUCTION = "production"


ACCOUNT_KIND_LABELS: dict[AccountKind, str] = {
    AccountKind.SANDBOX: "Песочница",
    AccountKind.PRODUCTION: "Боевой",
}


# Литерал-тип для kind у :class:`PendingOperation`. Перечислены все возможные
# виды операций, которые нуждаются в подтверждении пользователя. См.
# :mod:`core.pending_operations` для логики генерации.
PendingOperationKind = Literal[
    "initial_buy",
    "reinvest_buy",
    "top_up_buy",
    "put_offer_submit",
    "manual_sell",
]

PendingOperationStatus = Literal["action_required", "in_progress", "overdue", "blocked"]
PendingOperationUrgency = Literal["normal", "soon", "critical"]


# Направление сделки. Используется в :class:`TradeRecord` и
# :class:`data.trading_client.TradeOrder`. Литералом, а не StrEnum, чтобы
# напрямую маппиться на ``"BUY"`` / ``"SELL"`` из T-Invest API.
OrderDirection = Literal["BUY", "SELL"]


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
    put_offer_decision: PutOfferDecision = PutOfferDecision.PENDING
    # Глобальный идентификатор инструмента T-Invest. Заполняется при
    # переходе портфеля в режим торговли (через
    # :func:`data.tinvest_client.resolve_figi_for_isin`); в симуляции
    # обычно ``None``.
    figi: str | None = None
    # Фактическое количество лотов на брокерском счёте, актуализируется
    # :func:`core.portfolio_reconciler.reconcile_positions`. В симуляции
    # совпадает с :attr:`lots`; в режиме торговли может отличаться
    # (покупка ещё не подтверждена биржей, или произошла частичная
    # продажа) — расхождение подсвечивается в UI.
    actual_lots: int | None = None
    # Дата архивации позиции (погашение / полная продажа) в TRADING.
    closed_at: date | None = None

    @property
    def is_closed(self) -> bool:
        return self.closed_at is not None

    @property
    def bonds_count(self) -> int:
        """Количество облигаций в позиции (lots * lot_size)."""
        return self.lots * self.lot_size

    @property
    def has_drift(self) -> bool:
        """``True`` если фактических лотов на счёте меньше ожидаемого.

        Используется только в режиме торговли — в симуляции
        :attr:`actual_lots` всегда ``None`` и метод возвращает ``False``.
        """
        return self.actual_lots is not None and self.actual_lots != self.lots

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
            "put_offer_decision": self.put_offer_decision.value,
            "figi": self.figi,
            "actual_lots": self.actual_lots,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
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
            put_offer_decision=PutOfferDecision(
                data.get("put_offer_decision", PutOfferDecision.PENDING.value)
            ),
            figi=(str(data["figi"]) if data.get("figi") else None),
            actual_lots=(int(data["actual_lots"]) if data.get("actual_lots") is not None else None),
            closed_at=(
                date.fromisoformat(str(data["closed_at"])) if data.get("closed_at") else None
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


def _new_op_id() -> str:
    """UUID4 hex для PendingOperation / TradeRecord — короткий, JSON-friendly."""
    return uuid4().hex


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class FrozenForecast:
    """Скалярный снимок прогноза доходности в момент перехода в режим торговли.

    Прогноз фиксируется ОДИН раз — при `validate_account_for_attach` +
    подтверждении пользователем перехода в TRADING. Дальше эти числа не
    меняются никогда: пользователь видит обещанные показатели «на старте»
    отдельно от текущего динамического прогноза (`build_plan`) и от
    фактической доходности (`yield_calc`).

    Чтобы получить новый прогноз, нужно явно отвязать счёт (mode →
    SIMULATION) и снова перейти в TRADING — это сознательная UX-граница.

    Все суммы в ₽, доходности в годовых % (например, ``14.5`` = 14.5%).
    """

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


@dataclass
class PendingOperation:
    """Операция, ожидающая подтверждения пользователя в режиме торговли.

    Генерация в :mod:`core.pending_operations`:

    * ``initial_buy`` — стартовая покупка позиции (после перехода в TRADING).
    * ``reinvest_buy`` — покупка по слоту реинвестиции (когда
      ``trigger_date ≤ today``).
    * ``top_up_buy`` — покупка из распределения top-up свободного кэша.
    * ``put_offer_submit`` — напоминание подать оферту через чат брокера
      (API не умеет, см. AGENTS.md «Режим торговли → Пут-оферты»).
    * ``manual_sell`` — ручная продажа, инициирована пользователем из UI.

    Дедупликация: pending считается «закрытой», когда связанный
    :class:`TradeRecord` имеет статус ``EXECUTION_REPORT_STATUS_FILL``
    либо фактический баланс счёта подтверждает покупку/продажу.

    ``suggested_price_pct`` — лимитная цена в **% от номинала**
    (предзаполнена UI через ``last_price × (1 ± buffer)``), пользователь
    может изменить перед отправкой.

    ``top_up_batch_id`` — общий идентификатор «волны» top-up
    распределения. Если пользователь отменяет всю партию, по batch_id
    откатывается ``Portfolio.last_top_up_processed_at`` (см. AGENTS.md).
    """

    kind: PendingOperationKind
    isin: str
    name: str
    lots: int
    id: str = field(default_factory=_new_op_id)
    figi: str | None = None
    suggested_price_pct: float | None = None
    due_date: date | None = None
    reason: str = ""
    slot_id: str | None = None
    top_up_batch_id: str | None = None
    submitted_request_uid: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    status: PendingOperationStatus = "action_required"
    block_reason: str | None = None
    estimated_amount_rub: float | None = None
    face_value_rub: float | None = None
    lot_size: int | None = None
    aci_rub_per_bond: float | None = None
    active_order_id: str | None = None
    active_order_status: str | None = None
    active_order_lots: int | None = None
    active_order_price_pct: float | None = None
    active_order_total_rub: float | None = None
    active_order_commission_rub: float | None = None
    active_order_lots_executed: int | None = None
    active_order_bonds_count: int | None = None
    urgency: PendingOperationUrgency = "normal"
    chat_template: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "isin": self.isin,
            "name": self.name,
            "lots": self.lots,
            "figi": self.figi,
            "suggested_price_pct": self.suggested_price_pct,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "reason": self.reason,
            "slot_id": self.slot_id,
            "top_up_batch_id": self.top_up_batch_id,
            "submitted_request_uid": self.submitted_request_uid,
            "created_at": self.created_at,
            "status": self.status,
            "block_reason": self.block_reason,
            "estimated_amount_rub": self.estimated_amount_rub,
            "face_value_rub": self.face_value_rub,
            "lot_size": self.lot_size,
            "aci_rub_per_bond": self.aci_rub_per_bond,
            "active_order_id": self.active_order_id,
            "active_order_status": self.active_order_status,
            "active_order_lots": self.active_order_lots,
            "active_order_price_pct": self.active_order_price_pct,
            "active_order_total_rub": self.active_order_total_rub,
            "active_order_commission_rub": self.active_order_commission_rub,
            "active_order_lots_executed": self.active_order_lots_executed,
            "active_order_bonds_count": self.active_order_bonds_count,
            "urgency": self.urgency,
            "chat_template": self.chat_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingOperation:
        kind_raw = str(data.get("kind", "initial_buy"))
        # Жёстко проверяем literal — иначе runtime-краш при импорте старого
        # формата с неизвестным kind будет неинформативным.
        if kind_raw not in (
            "initial_buy",
            "reinvest_buy",
            "top_up_buy",
            "put_offer_submit",
            "manual_sell",
        ):
            raise ValueError(f"Unknown PendingOperation kind: {kind_raw!r}")
        return cls(
            id=str(data.get("id") or _new_op_id()),
            kind=kind_raw,  # type: ignore[arg-type]
            isin=str(data["isin"]),
            name=str(data.get("name", "")),
            lots=int(data.get("lots", 0)),
            figi=(str(data["figi"]) if data.get("figi") else None),
            suggested_price_pct=(
                float(data["suggested_price_pct"])
                if data.get("suggested_price_pct") is not None
                else None
            ),
            due_date=(date.fromisoformat(str(data["due_date"])) if data.get("due_date") else None),
            reason=str(data.get("reason", "")),
            slot_id=(str(data["slot_id"]) if data.get("slot_id") else None),
            top_up_batch_id=(str(data["top_up_batch_id"]) if data.get("top_up_batch_id") else None),
            submitted_request_uid=(
                str(data["submitted_request_uid"]) if data.get("submitted_request_uid") else None
            ),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            status=str(data.get("status", "action_required")),  # type: ignore[arg-type]
            block_reason=(str(data["block_reason"]) if data.get("block_reason") else None),
            estimated_amount_rub=(
                float(data["estimated_amount_rub"])
                if data.get("estimated_amount_rub") is not None
                else None
            ),
            face_value_rub=(
                float(data["face_value_rub"]) if data.get("face_value_rub") is not None else None
            ),
            lot_size=int(data["lot_size"]) if data.get("lot_size") is not None else None,
            aci_rub_per_bond=(
                float(data["aci_rub_per_bond"])
                if data.get("aci_rub_per_bond") is not None
                else None
            ),
            active_order_id=(str(data["active_order_id"]) if data.get("active_order_id") else None),
            active_order_status=(
                str(data["active_order_status"]) if data.get("active_order_status") else None
            ),
            active_order_lots=(
                int(data["active_order_lots"]) if data.get("active_order_lots") is not None else None
            ),
            active_order_price_pct=(
                float(data["active_order_price_pct"])
                if data.get("active_order_price_pct") is not None
                else None
            ),
            active_order_total_rub=(
                float(data["active_order_total_rub"])
                if data.get("active_order_total_rub") is not None
                else None
            ),
            active_order_commission_rub=(
                float(data["active_order_commission_rub"])
                if data.get("active_order_commission_rub") is not None
                else None
            ),
            active_order_lots_executed=(
                int(data["active_order_lots_executed"])
                if data.get("active_order_lots_executed") is not None
                else None
            ),
            active_order_bonds_count=(
                int(data["active_order_bonds_count"])
                if data.get("active_order_bonds_count") is not None
                else None
            ),
            urgency=str(data.get("urgency", "normal")),  # type: ignore[arg-type]
            chat_template=(str(data["chat_template"]) if data.get("chat_template") else None),
        )


@dataclass
class TradeRecord:
    """Аудит-запись отправленной/отменённой заявки T-Invest API.

    Полная история операций счёта — через ``operations.get_operations`` /
    ``cache/trade_orders.log``. Эта запись нужна для:

    * **Идемпотентности** — повторное нажатие «Купить» в UI не отправит
      вторую заявку, если уже есть TradeRecord с тем же
      ``request_uid``;
    * **UI** — показать список активных (NEW / PARTIALLY_FILL) и
      архивных (FILL / CANCELLED / REJECTED) заявок;
    * **Дедупликации pending operations** — если связанная по
      ``pending_op_id`` заявка ``FILL`` или ``CANCELLED``, pending
      помечается завершённой.

    ``status`` хранится строкой (значение
    ``EXECUTION_REPORT_STATUS_*`` из T-Invest), чтобы не плодить ещё
    один enum локально — справочник статусов меняется со стороны API.

    ``price_pct`` — цена ЛИМИТНОЙ заявки в **% от номинала** (как было
    отправлено). Для market-ордеров ``None``.
    """

    request_uid: str
    account_id: str
    account_kind: AccountKind
    figi: str
    direction: OrderDirection
    lots: int
    pending_op_id: str | None = None
    order_id: str | None = None
    price_pct: float | None = None
    status: str = "EXECUTION_REPORT_STATUS_NEW"
    submitted_at: str = field(default_factory=_utc_now_iso)
    last_state_checked_at: str | None = None
    total_order_amount_rub: float | None = None
    initial_commission_rub: float | None = None
    lots_executed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_uid": self.request_uid,
            "account_id": self.account_id,
            "account_kind": self.account_kind.value,
            "figi": self.figi,
            "direction": self.direction,
            "lots": self.lots,
            "pending_op_id": self.pending_op_id,
            "order_id": self.order_id,
            "price_pct": self.price_pct,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "last_state_checked_at": self.last_state_checked_at,
            "total_order_amount_rub": self.total_order_amount_rub,
            "initial_commission_rub": self.initial_commission_rub,
            "lots_executed": self.lots_executed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeRecord:
        direction_raw = str(data.get("direction", "BUY"))
        if direction_raw not in ("BUY", "SELL"):
            raise ValueError(f"Unknown TradeRecord direction: {direction_raw!r}")
        return cls(
            request_uid=str(data["request_uid"]),
            account_id=str(data["account_id"]),
            account_kind=AccountKind(data.get("account_kind", AccountKind.SANDBOX.value)),
            figi=str(data["figi"]),
            direction=direction_raw,  # type: ignore[arg-type]
            lots=int(data["lots"]),
            pending_op_id=(str(data["pending_op_id"]) if data.get("pending_op_id") else None),
            order_id=(str(data["order_id"]) if data.get("order_id") else None),
            price_pct=(float(data["price_pct"]) if data.get("price_pct") is not None else None),
            status=str(data.get("status", "EXECUTION_REPORT_STATUS_NEW")),
            submitted_at=str(data.get("submitted_at") or _utc_now_iso()),
            last_state_checked_at=(
                str(data["last_state_checked_at"]) if data.get("last_state_checked_at") else None
            ),
            total_order_amount_rub=(
                float(data["total_order_amount_rub"])
                if data.get("total_order_amount_rub") is not None
                else None
            ),
            initial_commission_rub=(
                float(data["initial_commission_rub"])
                if data.get("initial_commission_rub") is not None
                else None
            ),
            lots_executed=int(data.get("lots_executed", 0)),
        )

    @property
    def is_active(self) -> bool:
        """Заявка ещё на бирже (не исполнена, не отменена, не отклонена)."""
        terminal = {
            "EXECUTION_REPORT_STATUS_FILL",
            "EXECUTION_REPORT_STATUS_CANCELLED",
            "EXECUTION_REPORT_STATUS_REJECTED",
        }
        return self.status not in terminal


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
    # Если True (по умолчанию) — в автосборе, top-up и реинвесте только бумаги
    # с ``api_trade_available_flag`` из T-Invest (торгуемые через API).
    api_trade_only: bool = True
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
    last_synced_at: str | None = None
    # ISO-таймстамп последнего распределения top-up; INPUT-операции
    # после этой даты считаются «свежим» пополнением (см.
    # :func:`core.portfolio_reconciler.detect_top_up`).
    last_top_up_processed_at: str | None = None
    # Накопленная сумма всех уже распределённых top-up'ов в ₽.
    # Используется для расчёта «полного» бюджета при ребалансировке.
    acknowledged_top_ups_rub: float = 0.0
    # Метаданные волн top-up для отката незавершённых партий.
    top_up_batch_meta: dict[str, Any] = field(default_factory=dict)
    frozen_forecast: FrozenForecast | None = None
    pending_operations: list[PendingOperation] = field(default_factory=list)
    trade_records: list[TradeRecord] = field(default_factory=list)
    # Кэш проверки api_trade_available по (ISIN, direction) — избегаем bond_by на каждый sync.
    instrument_trade_cache: dict[str, dict[str, Any]] = field(default_factory=dict)

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
            "cash_balance_rub": self.cash_balance_rub,
            "mode": self.mode.value,
            "account_id": self.account_id,
            "account_kind": self.account_kind.value if self.account_kind else None,
            "account_label": self.account_label,
            "trading_started_at": self.trading_started_at,
            "last_synced_at": self.last_synced_at,
            "last_top_up_processed_at": self.last_top_up_processed_at,
            "acknowledged_top_ups_rub": self.acknowledged_top_ups_rub,
            "top_up_batch_meta": dict(self.top_up_batch_meta),
            "frozen_forecast": (self.frozen_forecast.to_dict() if self.frozen_forecast else None),
            "positions": [p.to_dict() for p in self.positions],
            "slots": [s.to_dict() for s in self.slots],
            "pending_operations": [op.to_dict() for op in self.pending_operations],
            "trade_records": [tr.to_dict() for tr in self.trade_records],
            "instrument_trade_cache": dict(self.instrument_trade_cache),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Portfolio:
        # Миграция: поля режима торговли отсутствуют в JSON старых портфелей,
        # дефолты ставят их в SIMULATION без attach-данных — никаких
        # breaking changes для существующих файлов.
        account_kind_raw = data.get("account_kind")
        frozen_raw = data.get("frozen_forecast")
        return cls(
            id=str(data.get("id") or _new_portfolio_id()),
            name=str(data["name"]),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
            initial_amount_rub=float(data["initial_amount_rub"]),
            horizon_date=date.fromisoformat(str(data["horizon_date"])),
            risk_profile=RiskProfile(data.get("risk_profile", RiskProfile.NORMAL.value)),
            api_trade_only=bool(data.get("api_trade_only", True)),
            cash_balance_rub=float(data.get("cash_balance_rub", 0.0)),
            mode=PortfolioMode(data.get("mode", PortfolioMode.SIMULATION.value)),
            account_id=(str(data["account_id"]) if data.get("account_id") else None),
            account_kind=(AccountKind(account_kind_raw) if account_kind_raw else None),
            account_label=(str(data["account_label"]) if data.get("account_label") else None),
            trading_started_at=(
                str(data["trading_started_at"]) if data.get("trading_started_at") else None
            ),
            last_synced_at=(str(data["last_synced_at"]) if data.get("last_synced_at") else None),
            last_top_up_processed_at=(
                str(data["last_top_up_processed_at"])
                if data.get("last_top_up_processed_at")
                else None
            ),
            acknowledged_top_ups_rub=float(data.get("acknowledged_top_ups_rub", 0.0)),
            top_up_batch_meta=dict(data.get("top_up_batch_meta", {})),
            frozen_forecast=(FrozenForecast.from_dict(frozen_raw) if frozen_raw else None),
            positions=[PortfolioPosition.from_dict(p) for p in data.get("positions", [])],
            slots=[ReinvestmentSlot.from_dict(s) for s in data.get("slots", [])],
            pending_operations=[
                PendingOperation.from_dict(op) for op in data.get("pending_operations", [])
            ],
            trade_records=[TradeRecord.from_dict(tr) for tr in data.get("trade_records", [])],
            instrument_trade_cache=dict(data.get("instrument_trade_cache", {})),
        )
