"""Расчёт купонного расписания и размера выплат по позиции."""

from __future__ import annotations

from datetime import date, timedelta

from bond_monitor.domain.portfolio.models import PortfolioPosition


def coupon_dates_in_range(
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


def coupon_payment_per_event(position: PortfolioPosition) -> float:
    """Размер одного купонного платежа по позиции (брутто, ₽)."""
    if not position.coupon_rate or not position.coupon_period_days:
        return 0.0
    per_bond = (
        position.face_value * (position.coupon_rate / 100.0) * (position.coupon_period_days / 365.0)
    )
    return per_bond * position.bonds_count
