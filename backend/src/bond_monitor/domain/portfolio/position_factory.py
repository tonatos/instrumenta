"""Создание и синхронизация позиций портфеля из live-данных MOEX."""

from __future__ import annotations

from datetime import date

from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.portfolio.models import (
    PortfolioPosition,
    PositionSourceType,
)
from bond_monitor.domain.portfolio.put_offer import (
    put_offer_buy_blocked,
    put_offer_submission_closed,
)


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
    и не должна попадать ни в :func:`position_end_date`, ни в напоминания о
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
    )


def sync_put_offer_from_bond(position: PortfolioPosition, bond: BondRecord) -> None:
    """Подтянуть окно пут-оферты из live-универса MOEX в позицию."""
    if bond.offer_date is None or bond.offer_date < position.purchase_date:
        return
    position.offer_date = bond.offer_date
    position.offer_submission_start = bond.offer_submission_start
    position.offer_submission_end = bond.offer_submission_end
    position.offer_price_pct = bond.offer_price_pct


def position_end_date(
    position: PortfolioPosition,
    horizon: date,
    *,
    today: date,
    assume_best_put_outcome: bool = False,
) -> date | None:
    """Эффективная дата возврата номинала по позиции.

    Ближайшая пут-оферта по номиналу или выше считается плановой датой
    выхода: бумаги подбираются под ``effective_date``, и cashflow должен
    отражать тот же горизонт удержания.
    """
    _ = assume_best_put_outcome  # сохранён для обратной совместимости вызовов
    if (
        position.offer_date is not None
        and position.offer_date > today
        and not put_offer_submission_closed(position, today)
        and position.offer_date <= horizon
    ):
        offer_price = position.offer_price_pct if position.offer_price_pct is not None else 100.0
        if offer_price >= 100.0:
            return position.offer_date

    return position.maturity_date
