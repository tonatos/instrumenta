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

from bond_monitor.domain.portfolio.models import Portfolio, PortfolioPosition, PositionSourceType
from bond_monitor.domain.portfolio.position_factory import position_from_bond
from bond_monitor.domain.bonds.models import BondRecord
from bond_monitor.domain.shared.money import Rub
from bond_monitor.domain.shared.position_math import position_cost_basis
from bond_monitor.domain.trading.ports import BrokerOperation, BrokerSnapshot

logger = logging.getLogger(__name__)


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
    input_operations: list[BrokerOperation]
    from_date: date  # точка отсчёта (last_top_up_processed_at или trading_started_at)

    @property
    def has_pending_top_up(self) -> bool:
        """Достаточно ли «свежих» средств для запуска UI-баннера."""
        # 100 ₽ — порог чтобы не зашумлять UI на копеечных операциях.
        return self.pending_top_up_rub > 100.0 and self.available_for_distribution_rub > 100.0


# Минимум свободного кэша для автораспределения без свежего INPUT
# (например после отмены партии top-up).
ORPHAN_CASH_TOP_UP_MIN_RUB = 5_000.0


def top_up_amount_to_distribute(
    detection: TopUpDetection,
    *,
    free_cash_rub: float,
    min_orphan_cash_rub: float = ORPHAN_CASH_TOP_UP_MIN_RUB,
) -> tuple[float, str | None]:
    """Сколько рублей распределить при sync: INPUT после watermark или «осиротевший» кэш."""
    if free_cash_rub <= 100.0:
        return 0.0, None
    if detection.has_pending_top_up:
        amount = min(float(detection.available_for_distribution_rub), free_cash_rub)
        return amount, None
    if free_cash_rub >= min_orphan_cash_rub:
        return free_cash_rub, (
            f"Свободный кэш {free_cash_rub:,.0f} ₽ на счёте без активной партии top-up — "
            "автораспределение."
        )
    return 0.0, None


# ── Validation ───────────────────────────────────────────────────────────────


def validate_account_for_attach(
    snapshot: BrokerSnapshot,
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


def collect_position_drifts(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
) -> list[PositionDrift]:
    """Актуальные расхождения план/факт после всех правок позиций."""
    drifts: list[PositionDrift] = []
    for position in portfolio.positions:
        if not position.figi:
            continue
        broker_pos = snapshot.bond_positions.get(position.figi)
        if broker_pos is None:
            actual_lots = 0
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
        if actual_lots != position.lots:
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
                    severity="warning",
                    message=message,
                )
            )
    return drifts


def reconcile_positions(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    operations: list[BrokerOperation] | None = None,
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

    # Сверка: для каждой локальной позиции с figi смотрим в snapshot.
    for position in portfolio.positions:
        if not position.figi:
            continue
        broker_pos = snapshot.bond_positions.get(position.figi)
        if broker_pos is None:
            position.actual_lots = 0
            continue
        if position.lot_size <= 0:
            continue
        actual_lots = broker_pos.quantity // position.lot_size
        position.actual_lots = actual_lots

    portfolio.cash_balance_rub = float(snapshot.money_rub)
    portfolio.last_synced_at = snapshot.fetched_at
    reconcile_acknowledged_top_ups(portfolio, snapshot)
    drifts = collect_position_drifts(portfolio, snapshot)

    return ReconciliationResult(
        updated_positions=portfolio.positions,
        drifts=drifts,
        money_rub=snapshot.money_rub,
        synced_at=snapshot.fetched_at,
    )


# ── Top-up detection ─────────────────────────────────────────────────────────


def detect_top_up(
    portfolio: Portfolio,
    operations: list[BrokerOperation],
    snapshot: BrokerSnapshot,
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

    input_ops: list[BrokerOperation] = []
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
    safe_cash_limit = Rub(
        max(0.0, float(snapshot.available_money_rub) * (1.0 - TOP_UP_COST_BUFFER))
    )
    available = Rub(min(float(pending), float(safe_cash_limit)))

    return TopUpDetection(
        pending_top_up_rub=pending,
        available_for_distribution_rub=available,
        input_operations=input_ops,
        from_date=reference_dt.date(),
    )


def reconcile_acknowledged_top_ups(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
) -> bool:
    """Синхронизировать ``acknowledged_top_ups_rub`` с фактическим капиталом на счёте.

    ``acknowledged_top_ups_rub = max(0, позиции + кэш − initial_amount)``.
    Обновляет и вверх (покупки вне batch), и вниз (отмена batch / частичное
    исполнение).
    """
    if not portfolio.is_trading:
        return False

    deployed = sum(position_cost_basis(position) for position in portfolio.positions)
    on_account = deployed + float(snapshot.available_money_rub)
    implied_top_ups = max(0.0, on_account - portfolio.initial_amount_rub)
    if abs(implied_top_ups - portfolio.acknowledged_top_ups_rub) > 0.01:
        portfolio.acknowledged_top_ups_rub = round(implied_top_ups, 2)
        return True
    return False


def _filled_buy_lots_via_app(portfolio: Portfolio, figi: str) -> int:
    total = 0
    for tr in portfolio.trade_records:
        if tr.figi != figi or tr.direction != "BUY":
            continue
        if tr.status == "EXECUTION_REPORT_STATUS_FILL":
            total += tr.lots_executed or tr.lots
    return total


def _max_cancelled_buy_lots(portfolio: Portfolio, figi: str) -> int:
    return max(
        (
            tr.lots - (tr.lots_executed or 0)
            for tr in portfolio.trade_records
            if tr.figi == figi
            and tr.direction == "BUY"
            and tr.status == "EXECUTION_REPORT_STATUS_CANCELLED"
        ),
        default=0,
    )


def migrate_legacy_adopted_holdings(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    universe_by_isin: dict[str, BondRecord],
) -> list[str]:
    """Разовая миграция: INITIAL с раздутыми lots → ADOPTED по факту счёта.

    Легаси-позиции, принятые старой версией ``adopt_orphan_holdings`` как
  ``INITIAL`` с ``lots = held + активная_заявка``, остаются раздутыми после
    отмены заявки. Схлопываем к ``actual + unfilled_active``, не трогая
    обычные частичные стартовые покупки.
    """
    from bond_monitor.domain.trading.pending_operations import (
        active_buy_unfilled_lots_for_figi,
        pending_top_up_lots_for_isin,
    )

    _ = universe_by_isin
    notes: list[str] = []
    if not portfolio.is_trading:
        return notes

    for pos in portfolio.positions:
        if pos.source != PositionSourceType.INITIAL:
            continue
        if not pos.figi or pos.actual_lots is None or pos.actual_lots <= 0:
            continue
        if pos.figi not in snapshot.bond_positions:
            continue

        unfilled = active_buy_unfilled_lots_for_figi(portfolio, pos.figi)
        pending_top_up = pending_top_up_lots_for_isin(portfolio, pos.isin)
        target_lots = pos.actual_lots + unfilled
        inflation = pos.lots - target_lots - pending_top_up
        if inflation <= 0:
            continue

        filled_via_app = _filled_buy_lots_via_app(portfolio, pos.figi)
        cancelled_lots = _max_cancelled_buy_lots(portfolio, pos.figi)
        should_migrate = filled_via_app < pos.actual_lots or cancelled_lots > inflation
        if not should_migrate:
            continue

        previous_lots = pos.lots
        pos.source = PositionSourceType.ADOPTED
        pos.lots = target_lots
        notes.append(
            f"Миграция позиции {pos.name}: цель {previous_lots} → {target_lots} лот(а) "
            f"по факту счёта (принята со счёта, ранее помечена как стартовая)."
        )
    return notes


def sweep_phantom_top_up_positions(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
) -> list[str]:
    """Удалить позиции из неисполненного top-up batch (is_new_position), которых нет на счёте."""
    from bond_monitor.domain.trading.pending_operations import (
        active_buy_unfilled_lots_for_figi,
        pending_top_up_lots_for_isin,
    )
    from bond_monitor.domain.trading.top_up import TopUpBatchMeta

    notes: list[str] = []
    if not portfolio.is_trading or not portfolio.top_up_batch_meta:
        return notes

    remove_isins: set[str] = set()
    for meta_dict in portfolio.top_up_batch_meta.values():
        meta = TopUpBatchMeta.from_dict(meta_dict)
        for alloc in meta.allocations:
            if not alloc.get("is_new_position"):
                continue
            isin = str(alloc.get("isin", ""))
            if not isin:
                continue
            pos = next((p for p in portfolio.positions if p.isin == isin), None)
            if pos is None or not pos.figi:
                continue
            actual = pos.actual_lots if pos.actual_lots is not None else 0
            if pos.figi in snapshot.bond_positions:
                broker = snapshot.bond_positions[pos.figi]
                lot_size = pos.lot_size or 1
                actual = broker.quantity // lot_size if lot_size > 0 else broker.lots
            unfilled = active_buy_unfilled_lots_for_figi(portfolio, pos.figi)
            pending_top = pending_top_up_lots_for_isin(portfolio, pos.isin)
            filled = _filled_buy_lots_via_app(portfolio, pos.figi)
            if actual <= 0 and unfilled <= 0 and pending_top <= 0 and filled <= 0:
                remove_isins.add(isin)

    if not remove_isins:
        return notes

    keep_positions: list[PortfolioPosition] = []
    for pos in portfolio.positions:
        if pos.isin in remove_isins:
            notes.append(
                f"Удалена фантомная позиция {pos.name}: бумага не появилась на счёте "
                f"после автораспределения top-up."
            )
            continue
        keep_positions.append(pos)
    portfolio.positions = keep_positions
    return notes


def reconcile_held_position_targets(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
) -> list[str]:
    """Схлопнуть раздутые цели у позиций, которые уже есть на счёте (реальность → lots)."""
    from bond_monitor.domain.trading.pending_operations import (
        active_buy_unfilled_lots_for_figi,
        pending_top_up_lots_for_isin,
    )

    notes: list[str] = []
    if not portfolio.is_trading:
        return notes

    for pos in portfolio.positions:
        if not pos.figi or pos.actual_lots is None or pos.actual_lots <= 0:
            continue
        if pos.figi not in snapshot.bond_positions:
            continue
        unfilled = active_buy_unfilled_lots_for_figi(portfolio, pos.figi)
        pending_top = pending_top_up_lots_for_isin(portfolio, pos.isin)
        target_lots = pos.actual_lots + unfilled + pending_top
        if pos.lots <= target_lots:
            continue
        previous = pos.lots
        pos.lots = target_lots
        if pos.source == PositionSourceType.INITIAL:
            pos.source = PositionSourceType.ADOPTED
        notes.append(
            f"{pos.name}: целевые лоты {previous} → {target_lots} "
            f"(факт {pos.actual_lots} + обязательства {unfilled + pending_top})."
        )
    return notes


def adopt_orphan_holdings(
    portfolio: Portfolio,
    snapshot: BrokerSnapshot,
    universe_by_isin: dict[str, BondRecord],
    *,
    today: date,
) -> list[str]:
    """Принять фактические холдинги со счёта в портфель («реальность определяет»)."""
    from bond_monitor.domain.trading.pending_operations import active_buy_unfilled_lots_for_figi

    notes: list[str] = []
    by_figi: dict[str, PortfolioPosition] = {p.figi: p for p in portfolio.positions if p.figi}

    for figi, broker_pos in snapshot.bond_positions.items():
        if broker_pos.quantity <= 0:
            continue

        bond = next((b for b in universe_by_isin.values() if b.figi == figi), None)
        if bond is None:
            if figi not in by_figi:
                notes.append(
                    f"На счёте {broker_pos.quantity} шт {broker_pos.ticker or figi[:8]} — "
                    "бумага не найдена в universe, позиция не создана."
                )
            continue

        lot_size = bond.lot_size or 1
        held_lots = broker_pos.lots if broker_pos.lots > 0 else broker_pos.quantity // lot_size
        unfilled_active = active_buy_unfilled_lots_for_figi(portfolio, figi)
        target_lots = held_lots + unfilled_active

        existing = by_figi.get(figi)
        if existing is not None:
            if existing.source == PositionSourceType.ADOPTED:
                if existing.actual_lots != held_lots:
                    existing.actual_lots = held_lots
                if existing.lots != target_lots:
                    existing.lots = target_lots
            continue

        position = position_from_bond(
            bond,
            lots=target_lots,
            purchase_date=today,
            source=PositionSourceType.ADOPTED,
        )
        position.figi = figi
        position.actual_lots = held_lots
        portfolio.positions.append(position)
        by_figi[figi] = position
        notes.append(
            f"Принята позиция {bond.name}: {held_lots} лот(а) на счёте"
            + (f", {unfilled_active} лот(а) в активной заявке" if unfilled_active else "")
            + "."
        )

    return notes


__all__ = [
    "AttachValidation",
    "PositionDrift",
    "ReconciliationResult",
    "TOP_UP_COST_BUFFER",
    "TopUpDetection",
    "ORPHAN_CASH_TOP_UP_MIN_RUB",
    "adopt_orphan_holdings",
    "collect_position_drifts",
    "detect_top_up",
    "migrate_legacy_adopted_holdings",
    "reconcile_acknowledged_top_ups",
    "reconcile_held_position_targets",
    "reconcile_positions",
    "sweep_phantom_top_up_positions",
    "top_up_amount_to_distribute",
    "validate_account_for_attach",
]
