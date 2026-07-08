"""Portfolio plan domain models and planning constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from bond_monitor.domain.portfolio.cashflow import CashflowEvent
from bond_monitor.domain.portfolio.models import (
    Portfolio,
    PortfolioPosition,
    ReinvestmentSlot,
)
from bond_monitor.domain.portfolio.policies import (
    DEFAULT_BOND_SELECTION_POLICY,
    DEFAULT_PLANNING_POLICY,
    DEFAULT_PORTFOLIO_ALLOCATION_POLICY,
)

_planning = DEFAULT_PLANNING_POLICY
_alloc = DEFAULT_PORTFOLIO_ALLOCATION_POLICY
_selection = DEFAULT_BOND_SELECTION_POLICY

REINVESTMENT_GAP_DAYS: int = _planning.reinvestment_gap_days
PUT_OFFER_REMINDER_DAYS: int = _planning.put_offer_reminder_days
MAX_REINVEST_DEPTH: int = _planning.max_reinvest_depth
COUPON_CASH_REINVEST_INTERVAL_DAYS: int = _planning.coupon_cash_reinvest_interval_days

MAX_POSITION_SHARE: float = _alloc.max_position_share
TARGET_POSITION_SHARE: float = _alloc.target_position_share
MAX_AUTO_POSITIONS: int = _alloc.max_auto_positions
MIN_AUTO_POSITIONS: int = _alloc.min_auto_positions
MIN_POSITION_AMOUNT_RUB: float = _alloc.min_position_amount_rub
MIN_POSITION_SHARE: float = _alloc.min_position_share

MIN_REPLACEMENT_HORIZON_DAYS: int = _selection.min_replacement_horizon_days
MIN_REINVEST_CLEAN_PRICE_PCT: float = _selection.min_clean_price_pct
SLOT_CANDIDATES_LIMIT: int = 30


@dataclass
class UpcomingPutOffer:
    """Запись о ближайшей пут-оферте, по которой требуется решение."""

    position: PortfolioPosition
    days_until: int
    days_until_submission_end: int | None
    submission_start: date | None
    submission_end: date | None
    offer_price_pct: float | None
    can_exercise: bool


@dataclass
class HeldPositionAtHorizon:
    """Описание позиции, которая ещё не погашена на ``horizon_date``."""

    position: PortfolioPosition
    estimated_value_rub: float
    valuation_source: str


@dataclass
class PortfolioValuePoint:
    """Снимок стоимости портфеля на дату внутри горизонта плана."""

    date: date
    cash_rub: float
    positions_value_rub: float
    total_value_rub: float


@dataclass
class PortfolioPlan:
    """Снимок портфеля + рассчитанный timeline до ``horizon_date``.

    План — производная сущность: он перестраивается при каждом обращении к
    UI на основе свежих рыночных данных. На диск сохраняются только сам
    портфель и явные пользовательские override-ы (см. :class:`Portfolio`).

    Итоговые поля разделены на «реализованные деньги» и «удерживаемые
    бумаги»:

    * ``final_cash_balance_rub`` — кэш на горизонте после всех погашений
      и реинвестиций;
    * ``held_positions_value_rub`` — рыночная (или face) стоимость бумаг,
      у которых ``maturity_date > horizon_date``;
    * ``final_portfolio_value_rub`` — сумма этих двух, удобная цифра
      «сколько у меня всего».

    ``total_net_profit_rub`` считается ОТ кэша (только то, что
    «материализовалось»), ``total_net_profit_with_held_rub`` — с учётом
    удерживаемых бумаг по их оценочной стоимости.
    """

    portfolio: Portfolio
    events: list[CashflowEvent] = field(default_factory=list)
    resolved_slots: list[ReinvestmentSlot] = field(default_factory=list)
    upcoming_put_offers: list[UpcomingPutOffer] = field(default_factory=list)
    held_positions: list[HeldPositionAtHorizon] = field(default_factory=list)
    # Все позиции, попавшие в worklist при построении плана: исходные +
    # phantom-позиции от реинвест-цепочек + coupon-cash phantom-ы.
    # Нужно, чтобы агрегаты типа взвешенного YTM считались по ВСЕМУ
    # плану, а не только по тому, что сейчас лежит в `portfolio.positions`.
    all_positions: list[PortfolioPosition] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    total_invested_rub: float = 0.0
    total_coupon_gross_rub: float = 0.0
    total_coupon_net_rub: float = 0.0
    total_tax_rub: float = 0.0
    total_redemption_rub: float = 0.0
    final_cash_balance_rub: float = 0.0
    held_positions_value_rub: float = 0.0
    final_portfolio_value_rub: float = 0.0
    total_net_profit_rub: float = 0.0
    total_net_profit_with_held_rub: float = 0.0
    # База вложенного капитала для расчёта прибыли и доходности.
    invested_capital_rub: float = 0.0
    # «Чистая YTM» текущих INITIAL-позиций, взвешенная по сумме покупки.
    # Это годовая доходность ТЕКУЩИХ позиций к их собственному
    # погашению, она НЕ описывает ожидаемую доходность всего портфеля
    # за весь горизонт (особенно при реинвестициях).
    weighted_ytm_net_pct: float | None = None
    # Средневзвешенная YTM нетто по ВСЕМ позициям плана (initial +
    # phantom-ы реинвест-цепочек). Эта цифра ближе к «средней годовой
    # доходности, на которую может рассчитывать портфель за весь
    # горизонт». Если она существенно ниже weighted_ytm_net_pct —
    # значит реинвестиции «разбавляют» доходность.
    weighted_ytm_net_full_pct: float | None = None
    # Эффективная ГОДОВАЯ доходность портфеля за весь горизонт: plan-XIRR
    # по датам внешних вложений и итоговой стоимости на горизонте.
    effective_annual_return_pct: float | None = None
    # Срок плана (для пересчёта эффективной доходности и формул в UI).
    horizon_days: int = 0
    # Точки роста стоимости портфеля (кэш + бумаги) от ``today`` до горизонта.
    value_timeline: list[PortfolioValuePoint] = field(default_factory=list)
