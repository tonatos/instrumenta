"""
Reconciler брокерского счёта T-Invest с локальной моделью портфеля.

Чистые функции (без Streamlit и без вызовов API). Принимают на вход уже
загруженные `AccountSnapshot` / `list[OperationRecord]` и возвращают
структурированные результаты сверки.

Используется в трёх местах:

* :func:`validate_account_for_attach` — на старте мастера перехода в
  TRADING. Проверяет, что счёт **строго чистый** (только RUB-кэш),
  иначе блокирует переход с понятным сообщением. См.
  [AGENTS.md → «Режим торговли → Привязка»].
* :func:`reconcile_positions` — на каждой синхронизации. Обновляет
  `PortfolioPosition.actual_lots`, выявляет дрейф (фактические лоты
  ≠ ожидаемые), синхронизирует `cash_balance_rub`.
* :func:`detect_top_up` — обнаруживает свободный кэш сверх плана
  (пополнения счёта пользователем). Источник — `OPERATION_TYPE_INPUT`
  после `last_top_up_processed_at` с верхним лимитом по фактическому
  `money_rub`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition
from bond_monitor.domain.shared.money import Rub
from bond_monitor.infrastructure.tinvest.trading_client import AccountSnapshot, OperationRecord

logger = logging.getLogger(__name__)


def _position_cost_basis(position: PortfolioPosition) -> float:
    if position.actual_lots is not None and position.actual_lots > 0:
        return position.purchase_dirty_price_rub * position.actual_lots * position.lot_size
    if position.purchase_amount_rub > 0:
        return position.purchase_amount_rub
    return position.purchase_dirty_price_rub * position.lots * position.lot_size


# Минимальный буфер RUB на счёте, который не распределяется через top-up:
# нужен на комиссии (~0.3% от объёма), НКД, проскальзывание. Реальная
# доступная сумма = money_rub × (1 − TOP_UP_COST_BUFFER).
TOP_UP_COST_BUFFER: float = 0.005


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class AttachValidation:
    """Результат валидации счёта для перехода в режим торговли.

    Используется UI-мастером: если ``can_attach == False`` — кнопка
    «Подтвердить» disabled, ``blockers`` показываются как красные
    сообщения. ``effective_initial_amount_rub`` — рекомендуемая сумма
    для предзаполнения поля «Стартовый бюджет» (учитывает реальный
    money_rub на счёте — см. правило «реальность определяющая»
    в AGENTS.md).
    """

    can_attach: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    effective_initial_amount_rub: Rub = Rub(0.0)


@dataclass
class PositionDrift:
    """Описание расхождения локальной позиции с фактом на счёте."""

    isin: str
    name: str
    expected_lots: int
    actual_lots: int
    severity: str  # 'warning' | 'critical'
    message: str


@dataclass
class ReconciliationResult:
    """Результат `reconcile_positions` — что изменилось после sync."""

    updated_positions: list[PortfolioPosition]
    drifts: list[PositionDrift]
    money_rub: Rub
    synced_at: str


@dataclass
class TopUpDetection:
    """Результат `detect_top_up` — сколько свежего кэша готово к распределению.

    ``available_for_distribution_rub`` — это и есть верхняя граница
    бюджета следующей «волны» покупок. Может быть меньше
    ``pending_top_up_rub`` если часть денег уже потрачена (или
    заблокирована под активные заявки).
    """

    pending_top_up_rub: Rub  # сумма всех INPUT с last_top_up_processed_at
    available_for_distribution_rub: Rub  # min(pending_top_up, money_rub - buffer)
    input_operations: list[OperationRecord]
    from_date: date  # точка отсчёта (last_top_up_processed_at или trading_started_at)

    @property
    def has_pending_top_up(self) -> bool:
        """Достаточно ли «свежих» средств для запуска UI-баннера."""
        # 100 ₽ — порог чтобы не зашумлять UI на копеечных операциях.
        return self.pending_top_up_rub > 100.0 and self.available_for_distribution_rub > 100.0


# ── Validation ───────────────────────────────────────────────────────────────


def validate_account_for_attach(
    snapshot: AccountSnapshot,
    portfolio: Portfolio,
) -> AttachValidation:
    """Strict-режим: счёт должен содержать ТОЛЬКО RUB-кэш.

    Блокеры (`can_attach=False`, в `blockers`):

    1. На счёте есть «чужие» инструменты (`other_instruments` непустой):
       акции, ETF, валюта ≠ RUB, фьючерсы, опционы. Пользователь должен
       их продать/вывести.
    2. На счёте есть облигации (`bond_positions` непустой). Считаем
       это «чужими» бумагами — портфель свежий и при переходе должен
       начинать с нуля. Импорт существующих позиций намеренно НЕ
       поддерживается (см. план: «изолированный бюджет, чистый счёт»).
    3. Свободного кэша меньше, чем `portfolio.initial_amount_rub`.

    Effective budget: если денег на счёте больше плана — поднимаем
    рекомендуемый стартовый бюджет до фактического money_rub
    (правило «реальность определяющая»). Пользователь сможет
    отредактировать значение в UI, но дефолт — фактический баланс.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    if snapshot.has_foreign_instruments:
        details = ", ".join(
            f"{ins.ticker or ins.figi} ({ins.instrument_type})"
            for ins in snapshot.other_instruments[:5]
        )
        more = (
            f" и ещё {len(snapshot.other_instruments) - 5}"
            if len(snapshot.other_instruments) > 5
            else ""
        )
        blockers.append(
            f"На счёте есть посторонние инструменты ({details}{more}). "
            "Продайте их или выберите другой счёт. "
            "Режим торговли работает только на «чистом» счёте."
        )

    if snapshot.bond_positions:
        bond_names = ", ".join(
            f"{p.ticker or p.figi[:6]} ({p.quantity} шт)"
            for p in list(snapshot.bond_positions.values())[:5]
        )
        more = (
            f" и ещё {len(snapshot.bond_positions) - 5}" if len(snapshot.bond_positions) > 5 else ""
        )
        blockers.append(
            f"На счёте уже есть облигации ({bond_names}{more}). "
            "Импорт существующих позиций не поддерживается — "
            "при переходе в режим торговли портфель собирается заново. "
            "Продайте бумаги или используйте другой счёт."
        )

    if snapshot.money_rub < portfolio.initial_amount_rub:
        shortage = portfolio.initial_amount_rub - snapshot.money_rub
        blockers.append(
            f"Свободных средств на счёте {snapshot.money_rub:,.2f} ₽, "
            f"а стартовый бюджет портфеля {portfolio.initial_amount_rub:,.2f} ₽. "
            f"Не хватает {shortage:,.2f} ₽ — пополните счёт или уменьшите бюджет портфеля."
        )

    effective_budget = Rub(max(float(snapshot.money_rub), portfolio.initial_amount_rub))
    if snapshot.money_rub > portfolio.initial_amount_rub and not blockers:
        extra = snapshot.money_rub - portfolio.initial_amount_rub
        warnings.append(
            f"На счёте {snapshot.money_rub:,.2f} ₽ — это больше планового бюджета "
            f"({portfolio.initial_amount_rub:,.2f} ₽) на {extra:,.2f} ₽. "
            f"Рекомендуем распределить всю сумму (поле «Стартовый бюджет» уже "
            f"подставит фактический баланс)."
        )

    return AttachValidation(
        can_attach=not blockers,
        blockers=blockers,
        warnings=warnings,
        effective_initial_amount_rub=effective_budget,
    )


# ── Reconciliation ───────────────────────────────────────────────────────────


def reconcile_positions(
    portfolio: Portfolio,
    snapshot: AccountSnapshot,
    operations: list[OperationRecord] | None = None,
) -> ReconciliationResult:
    """Сверить локальные позиции портфеля с фактическим состоянием счёта.

    Что делает:

    1. Для каждой `PortfolioPosition` обновляет `actual_lots` исходя из
       `snapshot.bond_positions[position.figi].quantity / lot_size`.
    2. Обновляет `Portfolio.cash_balance_rub` = `snapshot.money_rub`.
    3. Обновляет `Portfolio.last_synced_at`.
    4. Выявляет дрейф:

       * `actual_lots == 0` для позиции, ожидающей покупки (`lots > 0`) —
         **warning**, скорее всего ещё не подтверждена заявка.
       * `actual_lots < lots` (но > 0) — **warning**, частичное исполнение
         или ручная продажа.
       * `actual_lots > lots` — **warning**, лишние лоты (купили вручную
         или забытая старая позиция).
       * Облигация на счёте без `figi` matched к ни одной позиции
         портфеля — **critical**: что-то не так с привязкой, возможно
         счёт не «чистый».

    Мутирует объект `portfolio` (это сознательно — `reconcile_positions`
    вызывается из UI прямо перед `update_portfolio(portfolio)`).
    """
    drifts: list[PositionDrift] = []

    by_figi: dict[str, PortfolioPosition] = {p.figi: p for p in portfolio.positions if p.figi}

    # Сверка: для каждой локальной позиции с figi смотрим в snapshot.
    for position in portfolio.positions:
        if not position.figi:
            # Позиция без figi не может быть синхронизирована — это нормально
            # для свежих позиций до первого `resolve_figi_for_isin`. Не
            # обновляем `actual_lots`.
            continue
        broker_pos = snapshot.bond_positions.get(position.figi)
        if broker_pos is None:
            position.actual_lots = 0
            if position.lots > 0:
                drifts.append(
                    PositionDrift(
                        isin=position.isin,
                        name=position.name,
                        expected_lots=position.lots,
                        actual_lots=0,
                        severity="warning",
                        message=(
                            f"{position.name}: ожидалось {position.lots} лот(а), "
                            f"но на счёте этой бумаги нет. Подтвердите покупку "
                            f"в разделе «Ожидающие операции»."
                        ),
                    )
                )
            continue
        if position.lot_size <= 0:
            continue
        actual_lots = broker_pos.quantity // position.lot_size
        position.actual_lots = actual_lots
        if actual_lots != position.lots:
            severity = "warning"
            if actual_lots > position.lots:
                message = (
                    f"{position.name}: на счёте {actual_lots} лот(а), "
                    f"в плане {position.lots}. Лишние лоты не моделируются — "
                    f"либо купите их в другой портфель, либо обновите план."
                )
            else:
                message = (
                    f"{position.name}: на счёте {actual_lots} лот(а) из {position.lots} "
                    f"запланированных. Проверьте ожидающие операции."
                )
            drifts.append(
                PositionDrift(
                    isin=position.isin,
                    name=position.name,
                    expected_lots=position.lots,
                    actual_lots=actual_lots,
                    severity=severity,
                    message=message,
                )
            )

    # Обратная сверка: облигации на счёте, не покрытые ни одной позицией
    # портфеля. В strict-режиме это не должно случиться (валидация при
    # attach запрещает чужие облигации), но возможно если пользователь
    # купил бумагу вручную мимо портфеля. Critical-warning.
    for figi, broker_pos in snapshot.bond_positions.items():
        if figi not in by_figi and broker_pos.quantity > 0:
            drifts.append(
                PositionDrift(
                    isin="",
                    name=broker_pos.ticker or figi[:8],
                    expected_lots=0,
                    actual_lots=broker_pos.quantity,
                    severity="critical",
                    message=(
                        f"На счёте есть {broker_pos.quantity} шт {broker_pos.ticker or figi}, "
                        f"которые НЕ относятся к портфелю. "
                        f"Купили мимо плана? Решите вручную: добавьте позицию "
                        f"или продайте через брокера."
                    ),
                )
            )

    portfolio.cash_balance_rub = float(snapshot.money_rub)
    portfolio.last_synced_at = snapshot.fetched_at
    reconcile_acknowledged_top_ups(portfolio, snapshot)

    return ReconciliationResult(
        updated_positions=portfolio.positions,
        drifts=drifts,
        money_rub=snapshot.money_rub,
        synced_at=snapshot.fetched_at,
    )


# ── Top-up detection ─────────────────────────────────────────────────────────


def detect_top_up(
    portfolio: Portfolio,
    operations: list[OperationRecord],
    snapshot: AccountSnapshot,
) -> TopUpDetection:
    """Обнаружить свежие пополнения счёта пользователем.

    Алгоритм:

    1. Точка отсчёта — `portfolio.last_top_up_processed_at`
       (если ``None`` — `portfolio.trading_started_at`).
    2. Сумма всех `OPERATION_TYPE_INPUT` после этой точки = `pending_top_up_rub`.
    3. Верхний лимит распределения =
       `min(pending_top_up_rub, money_rub × (1 − TOP_UP_COST_BUFFER))`.
       Гарантирует, что после распределения на счёте останется буфер
       на комиссии и не уйдём в минус.

    Если у портфеля нет ни `last_top_up_processed_at`, ни
    `trading_started_at` (теоретически невозможно для TRADING-режима,
    но обработаем), возвращаем нулевую детекцию.
    """
    reference_iso = portfolio.last_top_up_processed_at or portfolio.trading_started_at
    if not reference_iso:
        return TopUpDetection(
            pending_top_up_rub=Rub(0.0),
            available_for_distribution_rub=Rub(0.0),
            input_operations=[],
            from_date=date.today(),
        )

    # ISO с тайм-зоной или без, парсим осторожно.
    try:
        reference_dt = datetime.fromisoformat(reference_iso)
    except ValueError:
        logger.warning("Invalid reference_iso for top_up detection: %s", reference_iso)
        return TopUpDetection(
            pending_top_up_rub=Rub(0.0),
            available_for_distribution_rub=Rub(0.0),
            input_operations=[],
            from_date=date.today(),
        )
    if reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=UTC)

    input_ops: list[OperationRecord] = []
    total: float = 0.0
    for op in operations:
        if op.type != "OPERATION_TYPE_INPUT":
            continue
        # Бывает что INPUT уже учтён в портфеле (`trading_started_at`
        # совпадает с датой первой INPUT). Берём строго ПОСЛЕ
        # reference_dt.
        op_dt = op.date if op.date.tzinfo else op.date.replace(tzinfo=UTC)
        if op_dt <= reference_dt:
            continue
        if op.payment_rub is None:
            continue
        if op.payment_rub <= 0:
            # INPUT-операция должна быть положительной, на всякий случай.
            continue
        input_ops.append(op)
        total += op.payment_rub

    pending = Rub(total)
    safe_cash_limit = Rub(max(0.0, float(snapshot.money_rub) * (1.0 - TOP_UP_COST_BUFFER)))
    available = Rub(min(float(pending), float(safe_cash_limit)))

    return TopUpDetection(
        pending_top_up_rub=pending,
        available_for_distribution_rub=available,
        input_operations=input_ops,
        from_date=reference_dt.date(),
    )


def reconcile_acknowledged_top_ups(
    portfolio: Portfolio,
    snapshot: AccountSnapshot,
) -> bool:
    """Синхронизировать ``acknowledged_top_ups_rub`` с фактическим капиталом на счёте.

    ``acknowledged_top_ups_rub = max(0, позиции + кэш − initial_amount)``.
    Обновляет и вверх (покупки вне batch), и вниз (отмена batch / частичное
    исполнение).
    """
    if not portfolio.is_trading:
        return False

    deployed = sum(_position_cost_basis(position) for position in portfolio.positions)
    on_account = deployed + float(snapshot.money_rub)
    implied_top_ups = max(0.0, on_account - portfolio.initial_amount_rub)
    if abs(implied_top_ups - portfolio.acknowledged_top_ups_rub) > 0.01:
        portfolio.acknowledged_top_ups_rub = round(implied_top_ups, 2)
        return True
    return False


__all__ = [
    "AttachValidation",
    "PositionDrift",
    "ReconciliationResult",
    "TOP_UP_COST_BUFFER",
    "TopUpDetection",
    "detect_top_up",
    "reconcile_acknowledged_top_ups",
    "reconcile_positions",
    "validate_account_for_attach",
]
