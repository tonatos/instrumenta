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

# Максимальная доля одной позиции в стартовом портфеле — жёсткий потолок
# для диверсификации. 0.30 = не более 30% бюджета в одну бумагу. Если у
# топ-кандидата лот дорогой и не помещается в целевую долю, мы можем
# временно увеличить долю до этого потолка, но не выше.
MAX_POSITION_SHARE: float = 0.30

# Желаемая доля одной позиции — ориентир алгоритма по диверсификации.
# 0.18 = ~5–6 позиций при достаточном бюджете. Алгоритм старается
# распределить деньги +/- равномерно вокруг этой доли.
TARGET_POSITION_SHARE: float = 0.18

# Сколько разных бумаг максимум подбирать в автосоставе. Ограничение чисто
# UX-овое: больше десятка позиций пользователю тяжело обозревать.
MAX_AUTO_POSITIONS: int = 10

# Минимальное число позиций, к которому стремимся (если хватает бюджета и
# подходящих бумаг). Меньше четырёх — это уже не диверсификация, а ставка.
MIN_AUTO_POSITIONS: int = 4

# Минимальная сумма одной позиции в рублях — отсекаем «огрызки» вроде
# одного лота на 1 000 ₽ при бюджете в 400 000 ₽. Реальный минимум —
# max(MIN_POSITION_AMOUNT_RUB, MIN_POSITION_SHARE × бюджет).
MIN_POSITION_AMOUNT_RUB: float = 5_000.0
MIN_POSITION_SHARE: float = 0.03

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
    # Эффективная ГОДОВАЯ доходность портфеля за весь горизонт, рассчитанная
    # из реализованного результата (cash + удерживаемые бумаги).
    # Формула: (final_portfolio_value / initial_amount) ^ (365 / horizon_days) − 1.
    # Это самая корректная цифра «сколько реально дал портфель в год».
    effective_annual_return_pct: float | None = None
    # Срок плана (для пересчёта эффективной доходности и формул в UI).
    horizon_days: int = 0


# ── Risk profile filter ──────────────────────────────────────────────────────


def risk_profile_filter(
    bonds: Sequence[BondRecord],
    profile: RiskProfile,
) -> list[BondRecord]:
    """Отфильтровать универс под выбранный риск-профиль.

    NORMAL — только LOW/MODERATE по шкале T-Invest, рейтинг ``≥ ruA-``,
    без субординации, без явных дефолтов. «Только для квалов» НЕ
    отсекаются — пользователь сам решает, может ли он их купить.

    AGGRESSIVE — все уровни риска, рейтинг ``≥ ruBB-``, разрешены амортизация,
    колл-оферта и субординация. Явные дефолты по-прежнему отсекаются —
    это уже не риск, а свершившийся факт.

    Бумаги без рейтинга в NORMAL отбрасываются (нельзя оценить риск
    эмитента); в AGGRESSIVE пропускаются — пользователь сознательно идёт
    на повышенный риск.

    Note:
        Раньше здесь стояло безусловное ``if bond.for_qual_investor_flag:
        continue`` — оно фильтровало бумаги с пометкой «только для
        квалифицированных инвесторов». Это убрано: статус «квал» — это
        регуляторное ограничение доступа, а не свойство риска бумаги
        как таковой. Если у пользователя есть статус квалифицированного
        инвестора, он сможет торговать этими бумагами; если нет — он
        просто их не увидит у брокера. Решать должен пользователь, а не
        универсальный фильтр приложения.
    """
    result: list[BondRecord] = []
    for bond in bonds:
        if bond.has_default or bond.has_technical_default:
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


def put_offer_buy_blocked(bond: BondRecord, as_of_date: date) -> str | None:
    """Проверить, можно ли покупать бумагу с учётом окна пут-оферты.

    Возвращает ``None``, если покупка допустима; иначе — причину отсечения.

    Типичный анти-паттерн: ``offer_date`` через неделю, а
    ``offer_submission_end`` уже прошёл — купить «под оферту» нельзя,
    YTM к оферте вводит в заблуждение, держать придётся до погашения.
    """
    if bond.offer_date is None or bond.offer_date <= as_of_date:
        return None
    if bond.offer_submission_end is None:
        return None
    if bond.offer_submission_end >= as_of_date:
        return None
    return (
        f"окно подачи по пут-оферте закрыто "
        f"{bond.offer_submission_end.isoformat()}, оферта "
        f"{bond.offer_date.isoformat()} — предъявить уже нельзя"
    )


def put_offer_can_exercise(position: PortfolioPosition, as_of_date: date) -> bool:
    """Можно ли **прямо сейчас** подать заявку на предъявление по пут-оферте."""
    if put_offer_submission_closed(position, as_of_date):
        return False
    if position.offer_date is None or position.offer_date <= as_of_date:
        return False
    return not (
        position.offer_submission_start is not None and as_of_date < position.offer_submission_start
    )


def put_offer_submission_closed(position: PortfolioPosition, as_of_date: date) -> bool:
    """Окно подачи заявки по пут-оферте уже закрыто (или оферты нет)."""
    if position.offer_date is None or position.offer_date <= as_of_date:
        return True
    if position.offer_submission_end is None:
        return False
    return as_of_date > position.offer_submission_end


def _sync_put_offer_from_bond(position: PortfolioPosition, bond: BondRecord) -> None:
    """Подтянуть окно пут-оферты из live-универса MOEX в позицию."""
    if bond.offer_date is None or bond.offer_date < position.purchase_date:
        return
    position.offer_date = bond.offer_date
    position.offer_submission_start = bond.offer_submission_start
    position.offer_submission_end = bond.offer_submission_end
    position.offer_price_pct = bond.offer_price_pct


def validate_replacement_bond(
    bond: BondRecord,
    *,
    slot_purchase_date: date,
    horizon: date,
) -> str | None:
    """Проверить, что бумага реально может быть куплена в слот на ``slot_purchase_date``.

    Возвращает None, если всё ок; иначе — короткое описание причины,
    почему бумага непригодна (используется в plan.notes).

    Это критический guard от data-bug-ов, где UI-селект слотов
    показывает бумагу с уже прошедшей датой погашения (см.
    :func:`ui.portfolio._render_single_slot` — там кандидаты беруутся из
    всего профильного универса без фильтра по дате). Если попытаться
    «купить» такую бумагу, планировщик эмитит maturity-событие в
    прошлом → cash приходит ДО списания на покупку → удвоение капитала.
    """
    if bond.maturity_date is None:
        return "у бумаги нет даты погашения"
    if bond.maturity_date <= slot_purchase_date:
        return (
            f"бумага гасится {bond.maturity_date.isoformat()}, что НЕ позже "
            f"даты покупки {slot_purchase_date.isoformat()}"
        )
    days_remaining = (bond.maturity_date - slot_purchase_date).days
    if days_remaining < MIN_REPLACEMENT_HORIZON_DAYS:
        return (
            f"до погашения {bond.maturity_date.isoformat()} осталось "
            f"всего {days_remaining} дн. (< MIN_REPLACEMENT_HORIZON_DAYS = "
            f"{MIN_REPLACEMENT_HORIZON_DAYS})"
        )
    if bond.maturity_date > horizon:
        # Это не блокер: бумага уйдёт за горизонт, превратится в
        # HeldPositionAtHorizon. Но в slot мы её принимать не хотим:
        # реинвест должен иметь чёткую дату возврата в кэш в пределах
        # плана, иначе цепочка обрывается.
        return (
            f"погашение {bond.maturity_date.isoformat()} позже горизонта "
            f"{horizon.isoformat()} — реинвест прервётся"
        )
    if bond.has_default or bond.has_technical_default:
        return "у бумаги статус дефолта / тех.дефолта"
    blocked = put_offer_buy_blocked(bond, slot_purchase_date)
    if blocked is not None:
        return blocked
    return None


def _remove_persisted_slot_override(portfolio: Portfolio, source_position_isin: str | None) -> None:
    """Удалить сохранённый ``confirmed_isin`` для слота с данной source-позицией.

    Используется планировщиком, когда он обнаруживает, что
    пользовательский override указывает на непригодную бумагу
    (см. :func:`validate_replacement_bond`). Иначе override застрял бы
    в ``cache/portfolios.json`` и при каждом rerun снова ломал план.

    Импорт ``update_portfolio`` локальный, чтобы избежать циклической
    зависимости ``core → data → core``.
    """
    if not source_position_isin:
        return
    from data.portfolios import update_portfolio

    changed = False
    for slot in portfolio.slots:
        if slot.source_position_isin == source_position_isin and slot.confirmed_isin is not None:
            slot.confirmed_isin = None
            changed = True
    if changed:
        # ``slots`` оставляем в файле — там может быть полезная история
        # (хотя без override-а), но если слот стал «пустым», лучше его
        # вычистить, чтобы не плодить мусор.
        portfolio.slots = [
            s
            for s in portfolio.slots
            if s.confirmed_isin is not None or s.source_position_isin != source_position_isin
        ]
        update_portfolio(portfolio)


def select_replacement(
    universe: Sequence[BondRecord],
    *,
    target_date: date,
    profile: RiskProfile,
    amount: float,
    horizon_date: date,
    key_rate: float,
    tax_rate: float,
) -> tuple[BondRecord, str] | tuple[None, None]:
    """Подобрать бумагу-замену для слота реинвестиции.

    Условия базового отбора (независимы от профиля):
        * есть рыночная цена;
        * стоимость 1 лота помещается в ``amount``;
        * дата погашения в окне ``[target_date + MIN_REPLACEMENT_HORIZON_DAYS,
          horizon_date]``.

    Профильные условия применяются с постепенным смягчением, чтобы деньги
    не простаивали в кэше, когда в точном окне нет идеальных бумаг:

    1. **Основной профиль** (``profile``): полный фильтр риска, рейтинга,
       субординации — все ограничения в силе.
    2. **Fallback → NORMAL**: если основной профиль не дал кандидатов,
       пробуем консервативный NORMAL (рейтинг ≥ ruA-, без субординации,
       без HIGH-риска). Применяется когда, например, в агрессивном портфеле
       под конец горизонта остались только длинные бумаги, а все ВДО уже
       погасились.
    3. **Fallback → любая без дефолта**: если и NORMAL пуст — берём любую
       пригодную по сроку бумагу без дефолта / тех.дефолта. Это крайняя
       мера: деньги в облигациях всё равно лучше, чем 0% в кэше.

    Во всех случаях скоринг проводится с весами *исходного* профиля:
    приоритет YTM / риска / ликвидности пользователя сохраняется, меняется
    только фильтр допустимых бумаг.

    Returns:
        ``(bond, note)`` — найденная бумага и строка-пометка для plan.notes
        (пустая строка если использован основной профиль);
        ``(None, None)`` если кандидаты не нашлись совсем.
    """
    if amount <= 0:
        return None, None
    min_maturity_date = target_date + timedelta(days=MIN_REPLACEMENT_HORIZON_DAYS)
    if min_maturity_date > horizon_date:
        return None, None

    def _candidates_for(bonds: Sequence[BondRecord]) -> list[BondRecord]:
        result: list[BondRecord] = []
        for bond in bonds:
            if put_offer_buy_blocked(bond, target_date) is not None:
                continue
            if not _has_usable_price(bond):
                continue
            lot_cost = bond.price_per_lot_rub or 0.0
            if lot_cost > amount:
                continue
            end = bond.maturity_date or bond.offer_date
            if end is None:
                continue
            if end < min_maturity_date or end > horizon_date:
                continue
            result.append(bond)
        return result

    def _best(candidates: list[BondRecord]) -> BondRecord | None:
        scored = score_bonds_for_profile(
            candidates,
            profile,
            key_rate=key_rate,
            tax_rate=tax_rate,
        )
        return scored[0] if scored else None

    # Шаг 1: основной профиль
    primary = _candidates_for(risk_profile_filter(universe, profile))
    if primary:
        bond = _best(primary)
        if bond:
            return bond, ""

    # Шаг 2: fallback → NORMAL (только если основной профиль не NORMAL)
    if profile != RiskProfile.NORMAL:
        normal_candidates = _candidates_for(risk_profile_filter(universe, RiskProfile.NORMAL))
        if normal_candidates:
            bond = _best(normal_candidates)
            if bond:
                return bond, (
                    f"профиль «{profile.value}» — нет кандидатов в окне "
                    f"[{target_date.isoformat()}, {horizon_date.isoformat()}]; "
                    f"выбрана бумага под NORMAL-профиль"
                )

    # Шаг 3: fallback → любая без дефолта
    no_default = [b for b in universe if not b.has_default and not b.has_technical_default]
    any_candidates = _candidates_for(no_default)
    if any_candidates:
        bond = _best(any_candidates)
        if bond:
            profiles_tried = (
                f"профиль «{profile.value}»"
                if profile == RiskProfile.NORMAL
                else f"профили «{profile.value}» и «{RiskProfile.NORMAL.value}»"
            )
            return bond, (
                f"{profiles_tried} не дали кандидатов в окне; "
                "выбрана лучшая по скору бумага без профильных ограничений"
            )

    return None, None


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

    Принципы распределения:

    1. **Диверсификация:** стремимся к ``MIN_AUTO_POSITIONS … MAX_AUTO_POSITIONS``
       позициям. Базовое число — ``initial_amount / TARGET_POSITION_SHARE``,
       но не меньше ``MIN_AUTO_POSITIONS`` и не больше ``MAX_AUTO_POSITIONS``.
    2. **Равномерность:** целевая сумма одной позиции
       ``target_per_position = initial_amount / target_count``. Алгоритм
       пытается покупать ровно столько лотов, чтобы вложенная сумма
       была близка к ``target_per_position``. Жёсткий потолок —
       ``MAX_POSITION_SHARE`` бюджета.
    3. **Отсутствие микропозиций:** минимум вложений в одну бумагу —
       ``max(MIN_POSITION_AMOUNT_RUB, MIN_POSITION_SHARE × бюджет)``.
       Если кандидат не помещается в этот минимум по 1 лоту — пропускаем
       (либо в конце пытаемся «добить» оставшимся бюджетом, см. шаг 5).
    4. **Профильный скор:** кандидаты упорядочены по
       :func:`score_bonds_for_profile`. Для AGGRESSIVE веса смещены в сторону
       YTM — это и есть «оптимизация по доходности», о которой говорил
       пользователь.
    5. **Доп-пополнение:** после первого прохода, если остался кэш ≥
       ``min_per_position``, пробуем увеличить позиции (по 1 лоту,
       начиная с самых прибыльных), не превышая ``MAX_POSITION_SHARE``.
       Так избегаем «огрызков» в конце.

    Returns:
        (positions, leftover_cash_rub, notes) — список купленных позиций,
        неинвестированный остаток (он попадёт в ``cash_balance_rub`` портфеля)
        и пояснения для UI.
    """
    notes: list[str] = []
    if initial_amount <= 0:
        return [], 0.0, ["Бюджет ≤ 0 — нечего распределять"]

    filtered = risk_profile_filter(universe, profile)
    candidates = [
        b
        for b in filtered
        if _has_usable_price(b)
        and b.maturity_date
        and b.maturity_date <= horizon_date
        and put_offer_buy_blocked(b, today) is None
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

    target_count = max(
        MIN_AUTO_POSITIONS,
        min(MAX_AUTO_POSITIONS, round(1.0 / TARGET_POSITION_SHARE)),
    )
    target_per_position = initial_amount / target_count
    max_per_position = initial_amount * MAX_POSITION_SHARE
    min_per_position = max(MIN_POSITION_AMOUNT_RUB, initial_amount * MIN_POSITION_SHARE)

    remaining = initial_amount
    positions: list[PortfolioPosition] = []
    bought_by_isin: dict[str, dict] = {}

    # Шаг 1: первый проход — каждая бумага получает ~target_per_position.
    for bond in scored:
        if remaining < min_per_position or len(positions) >= target_count:
            break
        lot_cost = bond.price_per_lot_rub or 0.0
        if lot_cost <= 0:
            continue

        # Скольки лотов хочется: ровно столько, чтобы вложить ~target.
        target_lots = max(1, round(target_per_position / lot_cost))
        cost_at_target = target_lots * lot_cost

        # Бумаги, у которых даже 1 лот не помещается в потолок 30% или в
        # минимальную позицию, — пропускаем. Это типично для дорогих
        # «джамбо»-выпусков с лотом 100 000+.
        if lot_cost > max_per_position:
            continue
        if cost_at_target < min_per_position:
            # Доразместим до min_per_position, если умещаемся в потолок.
            target_lots = int(min_per_position // lot_cost) + 1
            cost_at_target = target_lots * lot_cost
            if cost_at_target > max_per_position or cost_at_target > remaining:
                continue
        # Не превышаем потолок 30%.
        if cost_at_target > max_per_position:
            target_lots = int(max_per_position // lot_cost)
            cost_at_target = target_lots * lot_cost
        # Не превышаем оставшийся бюджет.
        if cost_at_target > remaining:
            target_lots = int(remaining // lot_cost)
            cost_at_target = target_lots * lot_cost
        if target_lots < 1 or cost_at_target < min_per_position:
            continue

        positions.append(position_from_bond(bond, lots=target_lots, purchase_date=today))
        bought_by_isin[bond.isin] = {"bond": bond, "lots": target_lots, "cost": cost_at_target}
        remaining -= cost_at_target

    # Шаг 2: добавочные лоты в уже купленные бумаги, чтобы съесть остаток.
    # Идём в порядке скоринга (самые прибыльные первыми) и докидываем по
    # одному лоту, пока остаток ≥ стоимости лота и доля не уперлась в
    # MAX_POSITION_SHARE.
    if remaining >= min_per_position:
        changed = True
        while changed and remaining > 0:
            changed = False
            for bond in scored:
                state = bought_by_isin.get(bond.isin)
                if state is None:
                    continue
                lot_cost = state["bond"].price_per_lot_rub or 0.0
                if lot_cost <= 0 or lot_cost > remaining:
                    continue
                if state["cost"] + lot_cost > max_per_position:
                    continue
                state["lots"] += 1
                state["cost"] += lot_cost
                remaining -= lot_cost
                changed = True
                if remaining < lot_cost:
                    break

        # Применяем накопленные доп-лоты к позициям.
        for pos in positions:
            state = bought_by_isin.get(pos.isin)
            if state is None or state["lots"] == pos.lots:
                continue
            new_lots = state["lots"]
            pos.lots = new_lots
            pos.purchase_amount_rub = pos.purchase_dirty_price_rub * new_lots * pos.lot_size

    # Шаг 3: если набрали меньше MIN_AUTO_POSITIONS и есть кэш — пробуем
    # добавить ещё одну бумагу (даже если она «дорогая» в смысле лота).
    if len(positions) < MIN_AUTO_POSITIONS and remaining >= min_per_position:
        for bond in scored:
            if bond.isin in bought_by_isin:
                continue
            lot_cost = bond.price_per_lot_rub or 0.0
            if lot_cost <= 0 or lot_cost > remaining or lot_cost > max_per_position:
                continue
            max_lots = min(
                int(remaining // lot_cost),
                int(max_per_position // lot_cost),
            )
            if max_lots < 1:
                continue
            cost = max_lots * lot_cost
            if cost < min_per_position:
                continue
            positions.append(position_from_bond(bond, lots=max_lots, purchase_date=today))
            bought_by_isin[bond.isin] = {"bond": bond, "lots": max_lots, "cost": cost}
            remaining -= cost
            if len(positions) >= MIN_AUTO_POSITIONS or remaining < min_per_position:
                break

    if not positions:
        notes.append(
            "Не нашлось бумаг, помещающихся в правила диверсификации (одна позиция "
            f"должна быть не меньше {min_per_position:,.0f} ₽ и не больше "
            f"{max_per_position:,.0f} ₽). Увеличьте бюджет или смягчите профиль."
        )
    else:
        notes.append(
            f"Распределение: {len(positions)} позиций по ~"
            f"{format_share(target_per_position, initial_amount)} бюджета каждая "
            f"(потолок {MAX_POSITION_SHARE * 100:.0f}%, минимум "
            f"{min_per_position:,.0f} ₽)."
        )
        if remaining >= min_per_position:
            notes.append(
                f"Остаток {remaining:,.0f} ₽ не вложен — недостаточно для очередной "
                "позиции по правилам диверсификации (можно добавить вручную "
                "через форму ниже)."
            )

    return positions, remaining, notes


def format_share(value: float, total: float) -> str:
    """Форматирование доли как ``18% (72 000 ₽)`` для пояснений."""
    if total <= 0:
        return f"{value:,.0f} ₽"
    pct = value / total * 100
    return f"{pct:.0f}% ({value:,.0f} ₽)"


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

    ``offer_date`` нормализуется: если у бумаги в ``BondRecord`` указана
    дата оферты, которая уже прошла относительно ``purchase_date``
    (типичный случай для фантомных reinvest-позиций, которые покупаются
    через несколько месяцев после исходной даты оферты бумаги), —
    обнуляем её. Прошедшая оферта не применима к свежекупленной позиции
    и не должна попадать ни в `_position_end_date`, ни в напоминания о
    пут-офертах.
    """
    clean_pct = bond.last_price or 0.0
    dirty_per_bond = bond.dirty_price_rub or 0.0
    aci_per_bond = bond.accrued_interest or 0.0
    bonds_count = lots * bond.lot_size
    offer_date = bond.offer_date if bond.offer_date and bond.offer_date >= purchase_date else None
    if offer_date and put_offer_buy_blocked(bond, purchase_date):
        offer_date = None
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
        offer_date=offer_date,
        offer_submission_start=bond.offer_submission_start if offer_date else None,
        offer_submission_end=bond.offer_submission_end if offer_date else None,
        offer_price_pct=bond.offer_price_pct if offer_date else None,
        coupon_period_days=bond.coupon_period_days,
        next_coupon_date=bond.next_coupon_date,
        source=source,
        put_offer_decision=PutOfferDecision.PENDING,
    )


# ── Plan builder ─────────────────────────────────────────────────────────────


def _position_end_date(position: PortfolioPosition, horizon: date, *, today: date) -> date | None:
    """Эффективная дата возврата номинала по позиции."""
    if (
        position.put_offer_decision == PutOfferDecision.EXERCISE
        and position.offer_date is not None
        and not put_offer_submission_closed(position, today)
    ):
        return position.offer_date
    return position.maturity_date


def _coupon_dates_in_range(
    position: PortfolioPosition,
    end_date: date,
) -> list[date]:
    """Даты купонных выплат в диапазоне ``(purchase_date, end_date]``.

    Используем ``next_coupon_date`` как якорь и шагаем по
    ``coupon_period_days``. Это важно: у короткой бумаги, где
    ``purchase_date + coupon_period_days`` лежит ЗА датой погашения,
    реальный следующий (и последний) купон всё равно есть — эмитент
    выплачивает его вместе с номиналом в дату погашения. Якорь по
    ``next_coupon_date`` (берётся из MOEX) корректно ловит этот случай:
    последний купон обычно совпадает с ``maturity_date``.

    Если у позиции нет ``next_coupon_date`` (бумага без расписания) —
    fallback на ``purchase_date + period`` (как было раньше). Это
    консервативная оценка для бумаг без явного графика.
    """
    if not position.coupon_period_days or position.coupon_period_days <= 0:
        return []
    if not position.coupon_rate or position.coupon_rate <= 0:
        return []
    period = timedelta(days=position.coupon_period_days)
    if position.next_coupon_date is not None:
        current = position.next_coupon_date
        # ``next_coupon_date`` мог оказаться раньше даты покупки (если
        # бумага добавлена задним числом) — сдвинем вперёд, чтобы не
        # засчитать прошлые купоны как доход портфеля.
        while current <= position.purchase_date:
            current = current + period
    else:
        current = position.purchase_date + period
    dates: list[date] = []
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
    # Подтягиваем окна пут-оферт из live-универса в сохранённые позиции.
    for pos in portfolio.positions:
        live_bond = universe_by_isin.get(pos.isin)
        if live_bond is not None:
            _sync_put_offer_from_bond(pos, live_bond)

    # ISIN-ы, для которых уже добавлено напоминание о пут-оферте: одна
    # бумага не должна порождать несколько одинаковых UI-карточек (а ключ
    # ``st.button`` строится из ``portfolio.id + position.isin`` —
    # дубликаты валят рендер Streamlit).
    reminded_isins: set[str] = set()
    while worklist:
        position, depth = worklist.pop(0)
        plan.all_positions.append(position)
        _emit_position_events(
            position, plan, today, horizon, tax_rate, universe_by_isin=universe_by_isin
        )

        # Напоминание о пут-оферте — только для исходных позиций пользователя
        # (PENDING), фантомные позиции с ``REINVEST_*`` source тоже могут
        # иметь оферту, и их тоже хочется подсветить.
        if (
            position.offer_date is not None
            and position.put_offer_decision == PutOfferDecision.PENDING
            and today <= position.offer_date <= horizon
            and position.isin not in reminded_isins
        ):
            live_bond = universe_by_isin.get(position.isin)
            if live_bond is not None:
                _sync_put_offer_from_bond(position, live_bond)
            days_until = (position.offer_date - today).days
            days_until_sub_end: int | None = None
            if position.offer_submission_end is not None:
                days_until_sub_end = (position.offer_submission_end - today).days
            can_exercise = put_offer_can_exercise(position, today)
            submission_closed = put_offer_submission_closed(position, today)
            show_reminder = (
                days_until <= PUT_OFFER_REMINDER_DAYS
                or can_exercise
                or (
                    days_until_sub_end is not None
                    and 0 <= days_until_sub_end <= PUT_OFFER_REMINDER_DAYS
                )
            )
            if show_reminder:
                plan.upcoming_put_offers.append(
                    UpcomingPutOffer(
                        position=position,
                        days_until=days_until,
                        days_until_submission_end=days_until_sub_end,
                        submission_start=position.offer_submission_start,
                        submission_end=position.offer_submission_end,
                        offer_price_pct=position.offer_price_pct,
                        can_exercise=can_exercise and not submission_closed,
                    )
                )
                reminded_isins.add(position.isin)

        if (
            position.put_offer_decision == PutOfferDecision.EXERCISE
            and position.offer_date is not None
            and put_offer_submission_closed(position, today)
        ):
            plan.notes.append(
                f"{position.name}: решение «Предъявить» невозможно — окно подачи "
                f"по пут-оферте "
                f"{position.offer_submission_end.isoformat() if position.offer_submission_end else '—'} "
                f"уже закрыто. Расчёт идёт до погашения "
                f"{position.maturity_date.isoformat() if position.maturity_date else '—'}."
            )

        end_date = _position_end_date(position, horizon, today=today)
        if end_date is None or end_date > horizon:
            # Позиция не успевает погаситься в горизонте — фиксируем её как
            # «удерживаемую на горизонте». Стоимость на горизонте оцениваем
            # сначала по live-цене (если бумага есть в актуальном универсе),
            # иначе по номиналу × количество облигаций (бумаги обычно
            # подтягиваются к номиналу к погашению).
            live_bond = universe_by_isin.get(position.isin)
            if (
                live_bond is not None
                and live_bond.dirty_price_rub is not None
                and live_bond.dirty_price_rub > 0
            ):
                est_value = live_bond.dirty_price_rub * position.bonds_count
                valuation_source = "live MOEX (грязная цена × кол-во)"
            else:
                est_value = position.face_value * position.bonds_count
                valuation_source = "номинал × кол-во (нет рыночной цены)"
            plan.held_positions.append(
                HeldPositionAtHorizon(
                    position=position,
                    estimated_value_rub=est_value,
                    valuation_source=valuation_source,
                )
            )
            continue

        slot_purchase_date = end_date + timedelta(days=REINVESTMENT_GAP_DAYS)
        if slot_purchase_date > horizon:
            # Бумага гасится в горизонте, но реинвестировать уже некуда:
            # деньги придут «слишком поздно» и просто останутся в кэше
            # (maturity-событие уже эмитировано _emit_position_events).
            continue

        if depth >= MAX_REINVEST_DEPTH:
            plan.notes.append(
                f"{position.name}: достигнут предел глубины реинвестиций "
                f"({MAX_REINVEST_DEPTH}); дальнейшие цепочки не моделировались."
            )
            continue

        is_put = (
            position.put_offer_decision == PutOfferDecision.EXERCISE
            and position.offer_date is not None
            and not put_offer_submission_closed(position, today)
        )
        net_at_end = (
            _net_redemption_amount(position, tax_rate, is_put=is_put)
            if is_put
            else _net_redemption_amount(position, tax_rate)
        )

        slot = saved_slots_by_source.get(position.isin)
        if slot is None:
            suggested, fallback_note = select_replacement(
                universe,
                target_date=slot_purchase_date,
                profile=portfolio.risk_profile,
                amount=net_at_end,
                horizon_date=horizon,
                key_rate=key_rate,
                tax_rate=tax_rate,
            )
            if fallback_note:
                plan.notes.append(
                    f"Слот {slot_purchase_date.isoformat()} ({position.name}): {fallback_note}."
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
                suggested, fallback_note = select_replacement(
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
                if fallback_note:
                    plan.notes.append(
                        f"Слот {slot_purchase_date.isoformat()} ({position.name}): {fallback_note}."
                    )

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

        invalid_reason = validate_replacement_bond(
            target_bond,
            slot_purchase_date=slot_purchase_date,
            horizon=horizon,
        )
        if invalid_reason is not None:
            # Сбрасываем сохранённый битый confirmed_isin: при следующем
            # rerun планировщик предложит автозамену (или явно скажет, что
            # её нет). Иначе пользовательский override застрянет и будет
            # каждый раз генерировать абсурдный cashflow.
            cleared_confirmed = slot.confirmed_isin
            if cleared_confirmed:
                _remove_persisted_slot_override(portfolio, slot.source_position_isin)
                # ``_remove_persisted_slot_override`` мутирует тот же
                # объект слота в ``portfolio.slots`` (а это та же ссылка,
                # что в ``saved_slots_by_source`` и в ``plan.resolved_slots``),
                # поэтому отдельно ``slot.confirmed_isin = None``
                # выставлять не нужно.
                plan.notes.append(
                    f"Слот {end_date.isoformat()}: ваш override "
                    f"«{cleared_confirmed}» отклонён ({invalid_reason}). "
                    f"Override сброшен. Выберите другую бумагу или "
                    f"оставьте автозамену."
                )
            else:
                plan.notes.append(
                    f"Слот {end_date.isoformat()}: подобранная замена "
                    f"{target_bond.name} непригодна ({invalid_reason})."
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

    _finalize_plan_totals(plan, universe_by_isin, today=today, tax_rate=tax_rate)
    return plan


def _emit_position_events(
    position: PortfolioPosition,
    plan: PortfolioPlan,
    today: date,
    horizon: date,
    tax_rate: float,
    universe_by_isin: dict[str, BondRecord] | None = None,
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

    ``universe_by_isin`` нужен для бэкфилла ``next_coupon_date`` у
    позиций, сохранённых до того, как поле было добавлено: если у
    позиции дата неизвестна, но бумага есть в актуальном универсе MOEX,
    мы её подтянем.
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

    if position.next_coupon_date is None and universe_by_isin is not None:
        live_bond = universe_by_isin.get(position.isin)
        if live_bond is not None and live_bond.next_coupon_date is not None:
            position.next_coupon_date = live_bond.next_coupon_date

    end_date = _position_end_date(position, horizon, today=today)
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
        position.put_offer_decision == PutOfferDecision.EXERCISE
        and position.offer_date is not None
        and not put_offer_submission_closed(position, today)
    )
    if is_put:
        price_suffix = (
            f" ({position.offer_price_pct:.0f}% номинала)"
            if position.offer_price_pct is not None
            else ""
        )
        desc = f"Пут-оферта по {position.name}{price_suffix}"
    else:
        desc = f"Погашение {position.name}"
    redemption = _net_redemption_amount(position, tax_rate, is_put=is_put)
    plan.events.append(
        CashflowEvent(
            date=end_date,
            kind="put_offer" if is_put else "maturity",
            amount_rub=redemption,
            description=desc,
            related_isin=position.isin,
            is_projected=end_date >= today,
        )
    )


def _net_redemption_amount(
    position: PortfolioPosition,
    tax_rate: float,
    *,
    is_put: bool = False,
) -> float:
    """Сумма к получению при погашении/пут-оферте после НДФЛ на курсовую разницу."""
    if is_put:
        price_pct = position.offer_price_pct or 100.0
        redemption_per_bond = position.face_value * (price_pct / 100.0)
    else:
        redemption_per_bond = position.face_value
    gross = redemption_per_bond * position.bonds_count
    clean_at_purchase = position.purchase_clean_price_pct / 100.0 * position.face_value
    taxable_gain = max(0.0, (redemption_per_bond - clean_at_purchase) * position.bonds_count)
    tax = taxable_gain * tax_rate
    return gross - tax


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

        candidate, fallback_note = select_replacement(
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
        # Defensive: select_replacement уже фильтрует по дате, но если
        # данные универса MOEX «съехали» (стали несвежими), повторно
        # валидируем — это страховка от того, что в coupon-cash попадёт
        # бумага, гасящаяся ДО purchase_date. Лучше пропустить слот, чем
        # сгенерировать абсурдный cashflow.
        if (
            validate_replacement_bond(candidate, slot_purchase_date=purchase_date, horizon=horizon)
            is not None
        ):
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
        plan.all_positions.append(phantom)
        events_before = len(plan.events)
        _emit_position_events(phantom, plan, today, horizon, tax_rate)
        new_events.extend(plan.events[events_before:])

        # Если бумага «купонной» реинвестиции не успевает погаситься —
        # фиксируем её как удерживаемую на горизонте.
        phantom_end = _position_end_date(phantom, horizon, today=today)
        if phantom_end is None or phantom_end > horizon:
            est_value = (candidate.dirty_price_rub or candidate.face_value) * phantom.bonds_count
            plan.held_positions.append(
                HeldPositionAtHorizon(
                    position=phantom,
                    estimated_value_rub=est_value,
                    valuation_source="live MOEX (грязная цена × кол-во)",
                )
            )

        invested = max_lots * lot_cost
        cash -= invested

    plan.resolved_slots.extend(new_slots)
    if new_slots:
        logger.info("Coupon-cash reinvest slots added: %d", len(new_slots))


def _event_sort_key(event: CashflowEvent) -> tuple[date, int]:
    """Сортировка событий: внутри одной даты сначала покупки, потом купоны/погашения."""
    order = {"purchase": 0, "coupon": 1, "maturity": 2, "put_offer": 2}
    return (event.date, order.get(event.kind, 3))


def _weighted_ytm(
    positions: Sequence[PortfolioPosition],
    universe_by_isin: dict[str, BondRecord],
) -> float | None:
    """Средневзвешенная YTM нетто, взвешенная по ``purchase_amount_rub``.

    Возвращает None, если ни одна позиция не нашла актуальную YTM в
    универсе. Используется и для текущих позиций, и для полного набора
    плана (с phantom-ами реинвест-цепочек).
    """
    weight_total = 0.0
    weighted_sum = 0.0
    for position in positions:
        bond = universe_by_isin.get(position.isin)
        if bond is None or bond.ytm_net is None:
            continue
        weight = position.purchase_amount_rub
        weight_total += weight
        weighted_sum += weight * bond.ytm_net
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total


def _finalize_plan_totals(
    plan: PortfolioPlan,
    universe_by_isin: dict[str, BondRecord],
    *,
    today: date,
    tax_rate: float,
) -> None:
    """Пересчитать агрегаты плана из ``events`` и ``portfolio``.

    ``universe_by_isin`` нужен для расчёта средневзвешенной YTM нетто по
    реально подтверждённым позициям. ``tax_rate`` — для восстановления
    брутто-купонов и налога на курсовую разницу из событий, эмитированных
    в нетто-форме. ``today`` — точка отсчёта для расчёта эффективной
    годовой доходности (горизонт меряется от неё до ``horizon_date``).
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

    # Налог на курсовую разницу считаем по ВСЕМ позициям плана (в т.ч.
    # phantom-позициям от реинвестиций): они тоже погашаются через
    # _net_redemption_amount, который уже вычитает этот налог из cashflow.
    # Если считать только по portfolio.positions — налог в total_tax_rub
    # будет занижен, хотя на итоговую прибыль это не влияет (деньги уже
    # правильно списаны в событиях).
    price_tax = 0.0
    for position in plan.all_positions:
        gain = _price_gain_total(position)
        if gain > 0:
            price_tax += gain * tax_rate

    held_positions_value = sum(h.estimated_value_rub for h in plan.held_positions)
    final_portfolio_value = cash + held_positions_value

    plan.total_invested_rub = round(total_invested, 2)
    plan.total_coupon_net_rub = round(total_coupon_net, 2)
    plan.total_coupon_gross_rub = round(total_coupon_gross, 2)
    plan.total_tax_rub = round(total_coupon_tax + price_tax, 2)
    plan.total_redemption_rub = round(total_redemption, 2)
    plan.final_cash_balance_rub = round(cash, 2)
    plan.held_positions_value_rub = round(held_positions_value, 2)
    plan.final_portfolio_value_rub = round(final_portfolio_value, 2)
    # Реализованная прибыль = только то, что превратилось в кэш к
    # горизонту, без учёта оценочной стоимости ещё не погашенных бумаг.
    plan.total_net_profit_rub = round(
        plan.final_cash_balance_rub - portfolio.initial_amount_rub,
        2,
    )
    # Прибыль с учётом удерживаемых бумаг — корректнее в случаях, когда
    # часть позиций уходит за горизонт: их оценочная стоимость
    # засчитывается как «недоматериализованная прибыль».
    plan.total_net_profit_with_held_rub = round(
        plan.final_portfolio_value_rub - portfolio.initial_amount_rub,
        2,
    )

    # Взвешенный YTM нетто по ТЕКУЩИМ позициям (только то, что сейчас
    # лежит в портфеле, без phantom-ов от реинвест-цепочек). Это
    # «годовая доходность текущих позиций к их собственным погашениям»;
    # она НЕ описывает ожидаемую доходность портфеля за горизонт при
    # наличии реинвестиций (нужно смотреть effective_annual_return_pct).
    weighted_initial = _weighted_ytm(portfolio.positions, universe_by_isin)
    if weighted_initial is not None:
        plan.weighted_ytm_net_pct = round(weighted_initial, 2)

    # YTM по ВСЕМ позициям плана (initial + phantom-ы от реинвест-цепочек):
    # ближе к «средней годовой доходности портфеля за горизонт».
    weighted_full = _weighted_ytm(plan.all_positions, universe_by_isin)
    if weighted_full is not None:
        plan.weighted_ytm_net_full_pct = round(weighted_full, 2)

    # Если реинвестиции «разбавили» доходность относительно initial —
    # явно подсветить это пользователю в notes плана. Порог 0.7 выбран
    # эмпирически: если средняя YTM по реинвестам < 70% от initial —
    # повод задуматься о расширении горизонта или ручном выборе слотов.
    if (
        weighted_initial is not None
        and weighted_initial > 0
        and weighted_full is not None
        and weighted_full < weighted_initial * 0.7
    ):
        dilution_pct = (1.0 - weighted_full / weighted_initial) * 100
        plan.notes.append(
            f"YTM реинвестиций ниже YTM текущих позиций: "
            f"{weighted_full:.1f}% против {weighted_initial:.1f}% "
            f"(разбавление ~{dilution_pct:.0f}%). На дату реинвеста в "
            f"окне до горизонта нет бумаг с такой же высокой YTM. "
            f"Варианты: (1) расширить горизонт портфеля, чтобы появились "
            f"более длинные / доходные бумаги; (2) вручную выбрать "
            f"альтернативу в слотах ниже; (3) принять, что короткие "
            f"бумаги «исчерпали» рыночную премию."
        )

    # Эффективная годовая доходность портфеля за весь горизонт —
    # рассчитывается из фактического результата плана (cash +
    # удерживаемые бумаги). Это единственная цифра, которую можно
    # сравнивать с депозитом / другими инструментами «по сумме сверху».
    horizon_days = (portfolio.horizon_date - today).days if today else 0
    plan.horizon_days = max(horizon_days, 0)
    if horizon_days > 0 and portfolio.initial_amount_rub > 0 and plan.final_portfolio_value_rub > 0:
        growth = plan.final_portfolio_value_rub / portfolio.initial_amount_rub
        # (1 + r)^(days/365) = growth → r = growth^(365/days) − 1
        try:
            annual_return = growth ** (365.0 / horizon_days) - 1.0
            plan.effective_annual_return_pct = round(annual_return * 100, 2)
        except (OverflowError, ValueError):
            plan.effective_annual_return_pct = None
