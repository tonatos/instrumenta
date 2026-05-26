"""
Бизнес-логика модуля «Портфель».

Содержит чистые функции (без побочных эффектов и без зависимости от Streamlit):

* :func:`risk_profile_filter` — фильтр универса под выбранный риск-профиль.
* :func:`auto_compose` — диверсифицированный автосостав начального портфеля.
* :func:`select_replacement` — подбор бумаги-замены для слота реинвестиции.
* :func:`build_plan` — моделирование cashflow и заполнение слотов
  реинвестиции до горизонта планирования.

Все функции принимают ``today`` параметром (а не зовут ``date.today()``
внутри), чтобы план был детерминирован и легко тестировался.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from core.bond_model import RATING_ORDER, BondRecord, RiskLevel
from core.portfolio_model import (
    Portfolio,
    PortfolioPosition,
    PositionSourceType,
    PutOfferDecision,
    ReinvestmentSlot,
    ReinvestmentTriggerReason,
    RiskProfile,
)
from core.scorer import score_bonds_for_profile

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

# Сеттлмент T+2 на MOEX + день на принятие решения = 2 рабочих дня. Считаем в
# календарных днях, чтобы не зависеть от производственного календаря.
REINVESTMENT_GAP_DAYS: int = 2

# За сколько дней до пут-оферты UI начинает показывать напоминание с выбором
# «предъявить» / «держать».
PUT_OFFER_REMINDER_DAYS: int = 30

# Максимальная доля одной позиции в стартовом портфеле — для диверсификации
# при автосоставе. 0.25 = не более 25% бюджета в одну бумагу.
MAX_POSITION_SHARE: float = 0.25

# Сколько разных бумаг максимум подбирать в автосоставе. Ограничение чисто
# UX-овое: больше десятка позиций пользователю тяжело обозревать.
MAX_AUTO_POSITIONS: int = 10

# Минимальная глубина оставшегося горизонта (в днях), при которой ещё имеет
# смысл подбирать замену в слоте — иначе купим бумагу, которая едва успеет
# прокрутить один купон.
MIN_REPLACEMENT_HORIZON_DAYS: int = 30

# Сколько уровней реинвестиций глубиной обрабатывать в :func:`build_plan`.
# Защита от теоретически бесконечной цепочки A → B → C → ... В реальной жизни
# с горизонтом 1–3 года реинвестиций редко больше 3–4.
MAX_REINVEST_DEPTH: int = 10

# Минимальный интервал между «купонными» реинвестициями: реинвестируем
# накопленный кэш не чаще чем раз в N дней, иначе план превратится в
# бесконечную цепочку микро-покупок.
COUPON_CASH_REINVEST_INTERVAL_DAYS: int = 180

# Кредитные пороги по национальной шкале, см. ``core.bond_model.RATING_ORDER``.
# `RATING_ORDER["ruA-"] == 6`, `RATING_ORDER["ruBB-"] == 0`.
_NORMAL_MIN_RATING_ORDINAL: int = RATING_ORDER["ruA-"]
_AGGRESSIVE_MIN_RATING_ORDINAL: int = RATING_ORDER["ruBB-"]


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class CashflowEvent:
    """Атомарное событие денежного потока в плане портфеля.

    Знак ``amount_rub``:
        * положительный → приток денег в кэш-баланс (купон, погашение, оферта);
        * отрицательный → отток (покупка бумаги).

    ``is_projected = True`` означает, что событие лежит в будущем и
    основано на текущих рыночных параметрах; история (если в портфеле есть
    позиции, купленные в прошлом) идёт с ``is_projected = False``.
    """

    date: date
    kind: str
    amount_rub: float
    description: str
    related_isin: str | None = None
    is_projected: bool = True


@dataclass
class UpcomingPutOffer:
    """Запись о ближайшей пут-оферте, по которой требуется решение."""

    position: PortfolioPosition
    days_until: int


@dataclass
class PortfolioPlan:
    """Снимок портфеля + рассчитанный timeline до ``horizon_date``.

    План — производная сущность: он перестраивается при каждом обращении к
    UI на основе свежих рыночных данных. На диск сохраняются только сам
    портфель и явные пользовательские override-ы (см. :class:`Portfolio`).
    """

    portfolio: Portfolio
    events: list[CashflowEvent] = field(default_factory=list)
    resolved_slots: list[ReinvestmentSlot] = field(default_factory=list)
    upcoming_put_offers: list[UpcomingPutOffer] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    total_invested_rub: float = 0.0
    total_coupon_gross_rub: float = 0.0
    total_coupon_net_rub: float = 0.0
    total_tax_rub: float = 0.0
    total_redemption_rub: float = 0.0
    final_cash_balance_rub: float = 0.0
    total_net_profit_rub: float = 0.0
    weighted_ytm_net_pct: float | None = None


# ── Risk profile filter ──────────────────────────────────────────────────────


def risk_profile_filter(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
) -> list[BondRecord]:
    """Отфильтровать универс под выбранный риск-профиль.

    NORMAL — только LOW/MODERATE по шкале T-Invest, рейтинг ``≥ ruA-``,
    без субординации, без «только для квалов», без дефолтных.

    AGGRESSIVE — все уровни риска, рейтинг ``≥ ruBB-``, разрешены амортизация
    и колл-оферта; явные дефолты по-прежнему отсекаются.

    Бумаги без рейтинга в NORMAL отбрасываются (нельзя оценить риск
    эмитента); в AGGRESSIVE пропускаются — пользователь сознательно идёт
    на повышенный риск.
    """
    result: list[BondRecord] = []
    for bond in bonds:
        if bond.has_default or bond.has_technical_default:
            continue
        if bond.for_qual_investor_flag:
            continue

        rating_ordinal: int | None = (
            RATING_ORDER.get(bond.credit_rating) if bond.credit_rating else None
        )

        if profile == RiskProfile.NORMAL:
            if bond.subordinated_flag:
                continue
            if bond.risk_level == RiskLevel.HIGH:
                continue
            if rating_ordinal is None:
                continue
            if rating_ordinal < _NORMAL_MIN_RATING_ORDINAL:
                continue
        elif profile == RiskProfile.AGGRESSIVE:
            if rating_ordinal is not None and rating_ordinal < _AGGRESSIVE_MIN_RATING_ORDINAL:
                continue

        result.append(bond)
    return result


# ── Selection helpers ────────────────────────────────────────────────────────


def _has_usable_price(bond: BondRecord) -> bool:
    """Бумага пригодна к покупке, если у неё есть положительная грязная цена."""
    return bond.price_per_lot_rub is not None and bond.price_per_lot_rub > 0


def select_replacement(
    universe: Sequence[BondRecord],
    *,
    target_date: date,
    profile: RiskProfile,
    amount: float,
    horizon_date: date,
    key_rate: float,
    tax_rate: float,
) -> BondRecord | None:
    """Подобрать бумагу-замену для слота реинвестиции.

    Условия отбора:
        * проходит фильтр риск-профиля;
        * есть рыночная цена;
        * стоимость 1 лота помещается в ``amount``;
        * дата погашения в окне ``[target_date + min_holding, horizon_date]``
          (бумага успевает «прокрутить» хотя бы один купон до горизонта).

    Среди подходящих возвращается лидер по
    :func:`core.scorer.score_bonds_for_profile` с весами выбранного профиля.
    Возвращает ``None``, если кандидаты не нашлись.
    """
    if amount <= 0:
        return None
    min_maturity_date = target_date + timedelta(days=MIN_REPLACEMENT_HORIZON_DAYS)
    if min_maturity_date > horizon_date:
        return None

    filtered = risk_profile_filter(universe, profile)
    candidates: list[BondRecord] = []
    for bond in filtered:
        if not _has_usable_price(bond):
            continue
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost > amount:
            continue
        # Срок отбираем по дате погашения; если её нет — используем offer_date
        # как консервативную оценку (бумага может быть выкуплена раньше).
        end = bond.maturity_date or bond.offer_date
        if end is None:
            continue
        if end < min_maturity_date or end > horizon_date:
            continue
        candidates.append(bond)

    if not candidates:
        return None

    scored = score_bonds_for_profile(
        candidates,
        profile,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )
    return scored[0] if scored else None


# ── Auto-compose ─────────────────────────────────────────────────────────────


def auto_compose(
    *,
    initial_amount: float,
    universe: Sequence[BondRecord],
    profile: RiskProfile,
    horizon_date: date,
    today: date,
    key_rate: float,
    tax_rate: float,
) -> tuple[list[PortfolioPosition], float, list[str]]:
    """Сформировать стартовый набор позиций под выбранный профиль и бюджет.

    Алгоритм:

    1. Отфильтровать универс по :func:`risk_profile_filter`.
    2. Оставить бумаги с погашением до ``horizon_date``.
    3. Отсортировать по :func:`score_bonds_for_profile` для выбранного профиля.
    4. Жадно набирать позиции сверху вниз, не превышая
       ``MAX_POSITION_SHARE`` × ``initial_amount`` на одну бумагу и
       ``MAX_AUTO_POSITIONS`` бумаг суммарно.

    Returns:
        (positions, leftover_cash_rub, notes) — список купленных позиций,
        неинвестированный остаток (он попадёт в ``cash_balance_rub`` портфеля)
        и пояснения для UI (например, «не нашли подходящих кандидатов»).
    """
    notes: list[str] = []
    if initial_amount <= 0:
        return [], 0.0, ["Бюджет ≤ 0 — нечего распределять"]

    filtered = risk_profile_filter(universe, profile)
    candidates = [
        b
        for b in filtered
        if _has_usable_price(b) and b.maturity_date and b.maturity_date <= horizon_date
    ]
    if not candidates:
        notes.append(
            "Под выбранный профиль и горизонт не нашлось ни одной подходящей бумаги. "
            "Расширьте горизонт, смягчите профиль или обновите данные MOEX."
        )
        return [], initial_amount, notes

    scored = score_bonds_for_profile(
        candidates,
        profile,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )

    max_per_position = initial_amount * MAX_POSITION_SHARE
    remaining = initial_amount
    positions: list[PortfolioPosition] = []

    for bond in scored:
        if remaining <= 0 or len(positions) >= MAX_AUTO_POSITIONS:
            break
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost <= 0 or lot_cost > remaining:
            continue
        budget_for_this = min(remaining, max_per_position)
        max_lots = int(budget_for_this // lot_cost)
        if max_lots < 1:
            continue
        invested = max_lots * lot_cost
        positions.append(position_from_bond(bond, lots=max_lots, purchase_date=today))
        remaining -= invested

    if not positions:
        notes.append(
            "Стоимость лота всех кандидатов превышает доступный бюджет. "
            "Увеличьте сумму или измените риск-профиль."
        )

    return positions, remaining, notes


def position_from_bond(
    bond: BondRecord,
    *,
    lots: int,
    purchase_date: date,
    source: PositionSourceType = PositionSourceType.INITIAL,
) -> PortfolioPosition:
    """Сконвертировать ``BondRecord`` (live из MOEX) в позицию портфеля.

    Используется и в автосоставе, и в ручном добавлении из UI, и при
    генерации фантомных позиций для слотов реинвестиции — все эти места
    единообразно фиксируют рыночные параметры на момент покупки.
    """
    clean_pct = bond.last_price or 0.0
    dirty_per_bond = bond.dirty_price_rub or 0.0
    aci_per_bond = bond.accrued_interest or 0.0
    bonds_count = lots * bond.lot_size
    return PortfolioPosition(
        isin=bond.isin,
        secid=bond.secid,
        name=bond.name,
        lots=lots,
        lot_size=bond.lot_size,
        purchase_clean_price_pct=clean_pct,
        purchase_dirty_price_rub=dirty_per_bond,
        purchase_aci_rub=aci_per_bond,
        purchase_date=purchase_date,
        purchase_amount_rub=dirty_per_bond * bonds_count,
        coupon_rate=bond.coupon_rate,
        face_value=bond.face_value,
        maturity_date=bond.maturity_date,
        offer_date=bond.offer_date,
        coupon_period_days=bond.coupon_period_days,
        source=source,
        put_offer_decision=PutOfferDecision.PENDING,
    )


# ── Plan builder ─────────────────────────────────────────────────────────────


def _position_end_date(position: PortfolioPosition, horizon: date) -> date | None:
    """Эффективная дата возврата номинала по позиции."""
    if position.put_offer_decision == PutOfferDecision.EXERCISE and position.offer_date is not None:
        return position.offer_date
    return position.maturity_date


def _coupon_dates_in_range(
    position: PortfolioPosition,
    end_date: date,
) -> list[date]:
    """Даты будущих купонных выплат в диапазоне ``(purchase_date, end_date]``.

    Считаем от ``purchase_date`` шагами по ``coupon_period_days``. Если у
    бумаги нет периода или ставки, возвращаем пустой список.
    """
    if not position.coupon_period_days or position.coupon_period_days <= 0:
        return []
    if not position.coupon_rate or position.coupon_rate <= 0:
        return []
    dates: list[date] = []
    period = timedelta(days=position.coupon_period_days)
    current = position.purchase_date + period
    while current <= end_date:
        dates.append(current)
        current = current + period
    return dates


def _coupon_payment_per_event(position: PortfolioPosition) -> float:
    """Размер одного купонного платежа по позиции (брутто, ₽)."""
    if not position.coupon_rate or not position.coupon_period_days:
        return 0.0
    per_bond = (
        position.face_value * (position.coupon_rate / 100.0) * (position.coupon_period_days / 365.0)
    )
    return per_bond * position.bonds_count


def _price_gain_total(position: PortfolioPosition) -> float:
    """Положительная разница «номинал − чистая цена покупки» × количество."""
    clean_at_purchase = position.purchase_clean_price_pct / 100.0 * position.face_value
    diff = position.face_value - clean_at_purchase
    return diff * position.bonds_count


def build_plan(
    portfolio: Portfolio,
    universe: Sequence[BondRecord],
    *,
    today: date,
    key_rate: float,
    tax_rate: float,
) -> PortfolioPlan:
    """Построить полный timeline портфеля до ``horizon_date``.

    Принципы расчёта:

    * Купонный доход — линейная аппроксимация по ставке и периоду:
      ``face × rate × period_days / 365`` за каждый купон. К каждому купону
      применяется ``tax_rate`` (НДФЛ).
    * Возврат номинала — в дату ``maturity_date`` (или ``offer_date`` при
      решении ``EXERCISE``). С положительной разницы (купили ниже номинала)
      удерживается НДФЛ.
    * Реинвестиция — слот создаётся для каждой позиции с эффективной датой
      окончания внутри горизонта. ``suggested_isin`` подбирается через
      :func:`select_replacement`. Если у слота уже есть ``confirmed_isin``,
      он используется как is — пользовательский выбор не перезаписывается.
    * Цепочки реинвестиций строятся итеративно (BFS по позициям) до
      :data:`MAX_REINVEST_DEPTH`.
    * Накопленный купонный кэш — между крупными событиями раз в
      :data:`COUPON_CASH_REINVEST_INTERVAL_DAYS` проверяется возможность
      реинвестировать накопленное в новую бумагу.
    """
    horizon = portfolio.horizon_date
    universe_by_isin: dict[str, BondRecord] = {b.isin: b for b in universe}

    plan = PortfolioPlan(portfolio=portfolio)

    # Существующие сохранённые слоты индексируем по ISIN исходной позиции,
    # чтобы пользовательский ``confirmed_isin`` не терялся при пересборке.
    saved_slots_by_source: dict[str, ReinvestmentSlot] = {}
    for slot in portfolio.slots:
        if slot.source_position_isin:
            saved_slots_by_source[slot.source_position_isin] = slot

    worklist: list[tuple[PortfolioPosition, int]] = [(p, 0) for p in portfolio.positions]
    while worklist:
        position, depth = worklist.pop(0)
        _emit_position_events(position, plan, today, horizon, tax_rate)

        # Напоминание о пут-оферте — только для исходных позиций пользователя
        # (PENDING), фантомные позиции с ``REINVEST_*`` source тоже могут
        # иметь оферту, и их тоже хочется подсветить.
        if (
            position.offer_date is not None
            and position.put_offer_decision == PutOfferDecision.PENDING
            and today <= position.offer_date <= horizon
        ):
            days_until = (position.offer_date - today).days
            if days_until <= PUT_OFFER_REMINDER_DAYS:
                plan.upcoming_put_offers.append(
                    UpcomingPutOffer(position=position, days_until=days_until)
                )

        end_date = _position_end_date(position, horizon)
        if end_date is None or end_date > horizon:
            continue

        slot_purchase_date = end_date + timedelta(days=REINVESTMENT_GAP_DAYS)
        if slot_purchase_date > horizon:
            continue

        if depth >= MAX_REINVEST_DEPTH:
            plan.notes.append(
                f"{position.name}: достигнут предел глубины реинвестиций "
                f"({MAX_REINVEST_DEPTH}); дальнейшие цепочки не моделировались."
            )
            continue

        net_at_end = _net_redemption_amount(position, tax_rate)
        is_put = (
            position.put_offer_decision == PutOfferDecision.EXERCISE
            and position.offer_date is not None
        )

        slot = saved_slots_by_source.get(position.isin)
        if slot is None:
            suggested = select_replacement(
                universe,
                target_date=slot_purchase_date,
                profile=portfolio.risk_profile,
                amount=net_at_end,
                horizon_date=horizon,
                key_rate=key_rate,
                tax_rate=tax_rate,
            )
            slot = ReinvestmentSlot(
                trigger_date=end_date,
                trigger_reason=(
                    ReinvestmentTriggerReason.PUT_OFFER
                    if is_put
                    else ReinvestmentTriggerReason.MATURITY
                ),
                expected_cash_rub=net_at_end,
                suggested_isin=suggested.isin if suggested else None,
                gap_days=REINVESTMENT_GAP_DAYS,
                source_position_isin=position.isin,
            )
        else:
            slot.expected_cash_rub = net_at_end
            slot.trigger_date = end_date
            slot.trigger_reason = (
                ReinvestmentTriggerReason.PUT_OFFER
                if is_put
                else ReinvestmentTriggerReason.MATURITY
            )
            slot.gap_days = REINVESTMENT_GAP_DAYS
            if not slot.suggested_isin and not slot.confirmed_isin:
                suggested = select_replacement(
                    universe,
                    target_date=slot_purchase_date,
                    profile=portfolio.risk_profile,
                    amount=net_at_end,
                    horizon_date=horizon,
                    key_rate=key_rate,
                    tax_rate=tax_rate,
                )
                if suggested:
                    slot.suggested_isin = suggested.isin

        plan.resolved_slots.append(slot)

        target_isin = slot.effective_isin
        if not target_isin:
            plan.notes.append(
                f"{position.name}: на дату {end_date.isoformat()} не нашлось "
                f"подходящей замены под профиль «{portfolio.risk_profile.value}». "
                f"Деньги останутся в кэш-балансе."
            )
            continue

        target_bond = universe_by_isin.get(target_isin)
        if target_bond is None or not _has_usable_price(target_bond):
            plan.notes.append(
                f"Слот {end_date.isoformat()}: бумага {target_isin} нет в "
                f"актуальном универсе MOEX или нет рыночной цены."
            )
            continue

        lot_cost = target_bond.price_per_lot_rub or 0.0
        max_lots = int(net_at_end // lot_cost) if lot_cost > 0 else 0
        if max_lots < 1:
            plan.notes.append(
                f"Слот {end_date.isoformat()}: ожидаемого кэша "
                f"({net_at_end:.0f} ₽) не хватает на 1 лот {target_bond.name} "
                f"({lot_cost:.0f} ₽)."
            )
            continue

        phantom = position_from_bond(
            target_bond,
            lots=max_lots,
            purchase_date=slot_purchase_date,
            source=(
                PositionSourceType.REINVEST_PUT_OFFER
                if is_put
                else PositionSourceType.REINVEST_MATURITY
            ),
        )
        worklist.append((phantom, depth + 1))

    # Купонный кэш: моделируем периодические попытки реинвестировать
    # накопленное между крупными событиями.
    _maybe_add_coupon_cash_reinvestments(
        plan,
        universe,
        today=today,
        key_rate=key_rate,
        tax_rate=tax_rate,
    )

    _finalize_plan_totals(plan, universe_by_isin, tax_rate=tax_rate)
    return plan


def _emit_position_events(
    position: PortfolioPosition,
    plan: PortfolioPlan,
    today: date,
    horizon: date,
    tax_rate: float,
) -> None:
    """Сгенерировать cashflow-события для одной позиции (purchase, coupons, redemption).

    Соглашение по покупкам:

    * Стоимость уже купленных INITIAL-позиций «зашита» в
      ``portfolio.cash_balance_rub`` (он содержит остаток после покупок).
      Для них событие «Покупка» не эмитится, иначе сумма будет
      вычтена дважды.
    * Будущие покупки (запланированные initial-позиции и все фантомы по
      слотам реинвестиции) попадают в timeline как события — их вклад
      проводится через cash-баланс плана.
    """
    is_future_purchase = position.purchase_date > today
    is_reinvestment = position.source != PositionSourceType.INITIAL
    if is_future_purchase or is_reinvestment:
        plan.events.append(
            CashflowEvent(
                date=position.purchase_date,
                kind="purchase",
                amount_rub=-position.purchase_amount_rub,
                description=f"Покупка {position.lots} лот(а) — {position.name}",
                related_isin=position.isin,
                is_projected=position.purchase_date >= today,
            )
        )

    end_date = _position_end_date(position, horizon)
    coupon_end = end_date if end_date and end_date <= horizon else horizon

    coupon_gross = _coupon_payment_per_event(position)
    if coupon_gross > 0:
        net_factor = 1.0 - tax_rate
        for d in _coupon_dates_in_range(position, coupon_end):
            plan.events.append(
                CashflowEvent(
                    date=d,
                    kind="coupon",
                    amount_rub=coupon_gross * net_factor,
                    description=f"Купон по {position.name}",
                    related_isin=position.isin,
                    is_projected=d >= today,
                )
            )

    if end_date is None or end_date > horizon:
        return

    is_put = (
        position.put_offer_decision == PutOfferDecision.EXERCISE and position.offer_date is not None
    )
    plan.events.append(
        CashflowEvent(
            date=end_date,
            kind="put_offer" if is_put else "maturity",
            amount_rub=_net_redemption_amount(position, tax_rate),
            description=(
                f"Пут-оферта по {position.name}" if is_put else f"Погашение {position.name}"
            ),
            related_isin=position.isin,
            is_projected=end_date >= today,
        )
    )


def _net_redemption_amount(position: PortfolioPosition, tax_rate: float) -> float:
    """Сумма к получению при погашении/оферте после НДФЛ на курсовую разницу."""
    face_back = position.face_value * position.bonds_count
    price_gain_taxable = max(0.0, _price_gain_total(position))
    tax = price_gain_taxable * tax_rate
    return face_back - tax


def _maybe_add_coupon_cash_reinvestments(
    plan: PortfolioPlan,
    universe: Sequence[BondRecord],
    *,
    today: date,
    key_rate: float,
    tax_rate: float,
) -> None:
    """Дополнительный проход: реинвестируем накопленный купонный кэш.

    Шагаем по таймлайну, считаем running cash. Каждые
    :data:`COUPON_CASH_REINVEST_INTERVAL_DAYS` проверяем: если cash достаточен
    для покупки лучшего кандидата под профиль, формируем coupon-cash слот и
    разворачиваем по нему фантомную позицию (с купонами и погашением,
    которые тоже добавляются в timeline).

    Цепочку «купонный кэш → купоны нового бонда → ещё один купонный кэш»
    не разворачиваем, чтобы не плодить бесконечные подциклы; пользователь
    увидит остаток в ``final_cash_balance_rub`` и сможет создать слот
    вручную.
    """
    portfolio = plan.portfolio
    horizon = portfolio.horizon_date

    sorted_events = sorted(plan.events, key=_event_sort_key)
    cash = portfolio.cash_balance_rub
    last_check = today

    new_events: list[CashflowEvent] = []
    new_slots: list[ReinvestmentSlot] = []

    for event in sorted_events:
        cash += event.amount_rub
        gap_days = (event.date - last_check).days
        if gap_days < COUPON_CASH_REINVEST_INTERVAL_DAYS:
            continue
        last_check = event.date
        purchase_date = event.date + timedelta(days=REINVESTMENT_GAP_DAYS)
        if purchase_date >= horizon - timedelta(days=MIN_REPLACEMENT_HORIZON_DAYS):
            continue
        if cash <= 0:
            continue

        candidate = select_replacement(
            universe,
            target_date=purchase_date,
            profile=portfolio.risk_profile,
            amount=cash,
            horizon_date=horizon,
            key_rate=key_rate,
            tax_rate=tax_rate,
        )
        if candidate is None:
            continue
        lot_cost = candidate.price_per_lot_rub or 0.0
        if lot_cost <= 0 or lot_cost > cash:
            continue

        max_lots = int(cash // lot_cost)
        if max_lots < 1:
            continue

        phantom = position_from_bond(
            candidate,
            lots=max_lots,
            purchase_date=purchase_date,
            source=PositionSourceType.REINVEST_COUPON_CASH,
        )
        slot = ReinvestmentSlot(
            trigger_date=event.date,
            trigger_reason=ReinvestmentTriggerReason.COUPON_CASH,
            expected_cash_rub=cash,
            suggested_isin=candidate.isin,
            confirmed_isin=None,
            gap_days=REINVESTMENT_GAP_DAYS,
            source_position_isin=None,
        )
        new_slots.append(slot)

        # Эмитим события phantom-позиции напрямую: рекурсивная цепочка
        # купонного-кэша не разворачивается (см. docstring).
        events_before = len(plan.events)
        _emit_position_events(phantom, plan, today, horizon, tax_rate)
        new_events.extend(plan.events[events_before:])

        invested = max_lots * lot_cost
        cash -= invested

    plan.resolved_slots.extend(new_slots)
    if new_slots:
        logger.info("Coupon-cash reinvest slots added: %d", len(new_slots))


def _event_sort_key(event: CashflowEvent) -> tuple[date, int]:
    """Сортировка событий: внутри одной даты сначала покупки, потом купоны/погашения."""
    order = {"purchase": 0, "coupon": 1, "maturity": 2, "put_offer": 2}
    return (event.date, order.get(event.kind, 3))


def _finalize_plan_totals(
    plan: PortfolioPlan,
    universe_by_isin: dict[str, BondRecord],
    *,
    tax_rate: float,
) -> None:
    """Пересчитать агрегаты плана из ``events`` и ``portfolio``.

    ``universe_by_isin`` нужен для расчёта средневзвешенной YTM нетто по
    реально подтверждённым позициям. ``tax_rate`` — для восстановления
    брутто-купонов и налога на курсовую разницу из событий, эмитированных
    в нетто-форме.
    """
    plan.events.sort(key=_event_sort_key)
    portfolio = plan.portfolio

    # Стартовый кэш = остаток после первоначальных покупок (см.
    # docstring _emit_position_events). События покупок INITIAL-позиций
    # сюда не входят, их стоимость уже учтена.
    cash = portfolio.cash_balance_rub
    initial_spent = sum(
        p.purchase_amount_rub
        for p in portfolio.positions
        if p.source == PositionSourceType.INITIAL and p.purchase_date <= portfolio.horizon_date
    )
    total_invested = initial_spent
    total_coupon_net = 0.0
    total_redemption = 0.0
    for event in plan.events:
        cash += event.amount_rub
        if event.kind == "purchase":
            total_invested += -event.amount_rub
        elif event.kind == "coupon":
            total_coupon_net += event.amount_rub
        elif event.kind in ("maturity", "put_offer"):
            total_redemption += event.amount_rub

    after_tax_factor = 1.0 - tax_rate
    if after_tax_factor > 0:
        total_coupon_gross = total_coupon_net / after_tax_factor
    else:
        total_coupon_gross = total_coupon_net
    total_coupon_tax = total_coupon_gross - total_coupon_net

    price_tax = 0.0
    for position in portfolio.positions:
        gain = _price_gain_total(position)
        if gain > 0:
            price_tax += gain * tax_rate

    plan.total_invested_rub = round(total_invested, 2)
    plan.total_coupon_net_rub = round(total_coupon_net, 2)
    plan.total_coupon_gross_rub = round(total_coupon_gross, 2)
    plan.total_tax_rub = round(total_coupon_tax + price_tax, 2)
    plan.total_redemption_rub = round(total_redemption, 2)
    plan.final_cash_balance_rub = round(cash, 2)
    # Чистая прибыль за весь горизонт = итоговый кэш − стартовый бюджет.
    # Бюджет (``initial_amount_rub``) уже включает в себя cash-balance после
    # начальных покупок, так что вычитать его отдельно нельзя.
    plan.total_net_profit_rub = round(
        plan.final_cash_balance_rub - portfolio.initial_amount_rub,
        2,
    )

    weight_total = 0.0
    weighted_ytm_sum = 0.0
    for position in portfolio.positions:
        bond = universe_by_isin.get(position.isin)
        if bond is None or bond.ytm_net is None:
            continue
        weight = position.purchase_amount_rub
        weight_total += weight
        weighted_ytm_sum += weight * bond.ytm_net
    if weight_total > 0:
        plan.weighted_ytm_net_pct = round(weighted_ytm_sum / weight_total, 2)
