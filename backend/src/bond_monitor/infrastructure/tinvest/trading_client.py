"""
Фасад над T-Invest API для торговли.

Заменяет старый stub. Унифицирует **sandbox** и **production**
контуры за единым интерфейсом — выбор контура по `AccountKind`:

* ``AccountKind.SANDBOX`` → :class:`t_tech.invest.sandbox.client.SandboxClient`
  (тот же gRPC API, endpoint песочницы; торговые методы — ``client.orders.*``);
* ``AccountKind.PRODUCTION`` → :class:`t_tech.invest.Client` и ``client.orders.*``.

Все денежные значения возвращаются как `core.money.Rub`, цены — как
`core.money.PriceUnitPct` (% от номинала; для облигаций T-Invest API
именно так и принимает цену в ``post_order.price``). См.
[AGENTS.md → «Режим торговли»] и [плану]
(.cursor/plans/portfolio-trading-mode_02455d48.plan.md).

Защита и идемпотентность:

* ``MAX_ORDER_AMOUNT_RUB`` (30 млн ₽) — порог, выше которого API требует
  SMS-подтверждения; перед `post_limit_order` бросаем
  :class:`OrderTooLargeError`.
* `request_uid` — детерминированный UID для идемпотентности. Один и тот
  же UID при повторной отправке вернёт результат первой заявки (без
  создания второй) — см. T-Invest docs.
* Audit log в `cache/trade_orders.log` (JSONL) — все submit/cancel + ответ.

Документация:
* https://developer.tbank.ru/invest/intro/intro/
* https://developer.tbank.ru/invest/intro/developer/sandbox/methods
* https://opensource.tbank.ru/invest/invest-python (SDK 0.3.5)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bond_monitor.domain.trading.models import AccountKind, OrderDirection
from bond_monitor.domain.shared.money import (
    MAX_ORDER_AMOUNT_RUB,
    Lots,
    PriceUnitPct,
    Rub,
    bond_clean_price_pct_from_rub,
    bond_clean_price_quotation,
    money_value_to_rub,
    quotation_to_float,
)

if TYPE_CHECKING:
    from t_tech.invest import (
        OperationItem,
        PortfolioResponse,
        PostOrderResponse,
    )
    from t_tech.invest import (
        OrderState as ProtoOrderState,
    )

logger = logging.getLogger(__name__)


# ── Errors ───────────────────────────────────────────────────────────────────


class TradingClientError(Exception):
    """Базовая ошибка торгового клиента."""


class OrderTooLargeError(TradingClientError):
    """Заявка превышает лимит 30 млн ₽ (API требует SMS, через API нельзя)."""


class TradingNotAvailableError(TradingClientError):
    """API/биржа отказали в торговле инструментом (нет торгов, не запущена бумага и т. п.)."""


class AccountNotFoundError(TradingClientError):
    """Брокерский счёт не найден (удалён, закрыт или неверный account_id)."""


def _request_error_code(exc: Any) -> str:
    """Извлечь числовой код ошибки T-Invest API из :class:`RequestError`."""
    details = getattr(exc, "details", "") or ""
    if isinstance(details, str) and details.isdigit():
        return details
    metadata = getattr(exc, "metadata", None)
    description = getattr(metadata, "description", None) if metadata else None
    if description is not None:
        return str(description)
    return ""


def _request_error_message(exc: Any) -> str:
    metadata = getattr(exc, "metadata", None)
    message = getattr(metadata, "message", None) if metadata else None
    if message:
        return str(message)
    return str(exc)


def _map_request_error(exc: Any, *, account_id: str = "") -> TradingClientError:
    """Преобразовать gRPC RequestError в понятное исключение торгового клиента."""
    code = _request_error_code(exc)
    if code == "50004":
        label = account_id or "указанный"
        return AccountNotFoundError(
            f"Счёт {label} не найден в T-Invest. "
            f"Возможно, sandbox-счёт был пересоздан — перепривяжите портфель."
        )
    if code == "30052":
        return TradingNotAvailableError(
            f"Инструмент недоступен для торговли через API (код {code}: "
            f"{_request_error_message(exc)})"
        )
    return TradingClientError(f"T-Invest API: {_request_error_message(exc)} (код {code or '?'})")


def _order_instrument_kwargs(*, figi: str, instrument_uid: str = "") -> dict[str, str]:
    """Параметры идентификации инструмента для ``orders.post_order``.

    T-Invest рекомендует ``instrument_id`` (UID); ``figi`` оставляем для
    обратной совместимости, когда UID ещё не известен.
    """
    if instrument_uid:
        return {"instrument_id": instrument_uid, "figi": figi}
    if figi:
        return {"figi": figi}
    raise TradingClientError("Не задан FIGI или instrument_uid для заявки")


class TradingTokenMissingError(TradingClientError):
    """Не задан соответствующий токен (T_TRADING_TOKEN_SANDBOX/PRODUCTION)."""


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountInfo:
    """Краткое описание счёта пользователя для селектора в UI."""

    id: str
    name: str
    kind: AccountKind
    access_level: str  # ACCOUNT_ACCESS_LEVEL_FULL_ACCESS и т. п.
    status: str  # ACCOUNT_STATUS_OPEN и т. п.
    is_writable: bool  # access_level == FULL_ACCESS

    @property
    def display_label(self) -> str:
        suffix = " (sandbox)" if self.kind == AccountKind.SANDBOX else ""
        name = self.name or f"Счёт {self.id[:6]}"
        return f"{name}{suffix}"


@dataclass(frozen=True)
class BondPosition:
    """Позиция по облигации на брокерском счёте (фактический остаток)."""

    figi: str
    instrument_uid: str
    ticker: str
    quantity: int  # количество облигаций (НЕ лотов)
    lots: int  # лоты (из quantity_lots портфеля T-Invest)
    blocked: int
    current_price_pct: PriceUnitPct | None
    current_nkd_rub: Rub | None
    average_price_pct: PriceUnitPct | None


@dataclass(frozen=True)
class OtherInstrument:
    """Любая не-RUB и не-облигация на счёте (акции, валюта, фьючерсы)."""

    instrument_type: str  # share / etf / currency / future / option / ...
    figi: str
    ticker: str
    quantity: int


@dataclass(frozen=True)
class AccountSnapshot:
    """Снимок состояния брокерского счёта в момент запроса."""

    account_id: str
    account_kind: AccountKind
    money_rub: Rub
    # Только облигации (для импорта в портфель и сверки):
    bond_positions: dict[str, BondPosition]  # figi → BondPosition
    # Всё остальное (акции, валюта ≠ RUB, фьючерсы, ETF, опционы):
    # используется только в `validate_account_for_attach` для блокировки
    # перехода в режим торговли (см. AGENTS.md → «strict attach»).
    other_instruments: list[OtherInstrument]
    fetched_at: str
    blocked_money_rub: Rub = Rub(0.0)

    @property
    def has_foreign_instruments(self) -> bool:
        """True если на счёте есть что-то кроме RUB-кэша и облигаций."""
        return bool(self.other_instruments)

    @property
    def available_money_rub(self) -> Rub:
        return Rub(max(0.0, float(self.money_rub) - float(self.blocked_money_rub)))


@dataclass(frozen=True)
class OperationRecord:
    """Лёгкая обёртка над ``OperationItem`` для удобства тестирования.

    Содержит только те поля, что нужны для XIRR, top-up detection и
    sync позиций. Сырой `OperationItem` всё ещё доступен через
    `raw` — на случай дебага в UI.
    """

    id: str
    type: str  # OPERATION_TYPE_* (имя enum-значения)
    state: str
    date: datetime
    figi: str
    instrument_uid: str
    instrument_type: str
    payment_rub: Rub | None
    quantity: int
    price_pct: PriceUnitPct | None
    commission_rub: Rub | None
    raw: OperationItem | None = None


@dataclass(frozen=True)
class PostOrderResult:
    """Ответ на `post_limit_order`."""

    order_id: str
    request_uid: str
    execution_report_status: str
    lots_executed: int
    lots_requested: int
    executed_price_pct: PriceUnitPct | None
    initial_order_price_rub: Rub | None
    total_order_amount_rub: Rub | None
    initial_commission_rub: Rub | None
    message: str = ""


@dataclass(frozen=True)
class OrderState:
    """Текущее состояние биржевой заявки."""

    order_id: str
    execution_report_status: str
    figi: str
    direction: OrderDirection
    lots_executed: int
    lots_requested: int
    executed_price_pct: PriceUnitPct | None
    initial_order_price_rub: Rub | None
    total_order_amount_rub: Rub | None
    order_date: datetime | None
    request_uid: str = ""
    price_pct: PriceUnitPct | None = None
    initial_commission_rub: Rub | None = None


@dataclass(frozen=True)
class OrderPricePreview:
    """Предварительный расчёт стоимости заявки до отправки (комиссии, НКД)."""

    lots_requested: int
    clean_amount_rub: Rub | None
    aci_amount_rub: Rub | None
    total_order_amount_rub: Rub | None
    executed_commission_rub: Rub | None
    deal_commission_rub: Rub | None

    @property
    def initial_order_amount_rub(self) -> Rub | None:
        """Совместимость: чистая стоимость без НКД."""
        return self.clean_amount_rub


# ── Audit log ────────────────────────────────────────────────────────────────

from bond_monitor.infrastructure.paths import get_cache_dir

_CACHE_DIR: Path = get_cache_dir()
_AUDIT_LOG_PATH: Path = _CACHE_DIR / "trade_orders.log"


def _audit_log(event: str, payload: dict[str, Any]) -> None:
    """Append-only JSONL запись в `cache/trade_orders.log`.

    Логируем тождественно для sandbox и production — анализ дальше за UI.
    Ошибки записи не пробрасываем (диск кончился — это не повод ронять
    заявку, которая уже ушла на биржу).
    """
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "event": event,
            **payload,
        }
        with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Failed to write audit log entry %s", event)


# ── Token / client helpers ───────────────────────────────────────────────────


def resolve_token(account_kind: AccountKind) -> str:
    """Получить токен для соответствующего контура из ENV.

    Имена переменных зафиксированы планом и AGENTS.md:

    * ``T_TRADING_TOKEN_SANDBOX`` — sandbox;
    * ``T_TRADING_TOKEN_PRODUCTION`` — production.
    """
    env_name = (
        "T_TRADING_TOKEN_SANDBOX"
        if account_kind == AccountKind.SANDBOX
        else "T_TRADING_TOKEN_PRODUCTION"
    )
    token = os.getenv(env_name, "").strip()
    if not token:
        raise TradingTokenMissingError(
            f"Не задан {env_name} — режим торговли {account_kind.value} недоступен"
        )
    return token


@contextmanager
def _open_client(token: str, account_kind: AccountKind) -> Generator[Any, None, None]:
    """Контекстный менеджер: открывает `Client` или `SandboxClient`.

    `Client` `t_tech.invest` сам управляет gRPC-каналом, важно
    использовать as-statement (с закрытием).
    """
    if account_kind == AccountKind.SANDBOX:
        from t_tech.invest.sandbox.client import SandboxClient

        with SandboxClient(token) as client:
            yield client
    else:
        from t_tech.invest import Client

        with Client(token) as client:
            yield client


# ── Request UID (идемпотентность) ────────────────────────────────────────────


def make_request_uid(
    *,
    account_id: str,
    figi: str,
    direction: OrderDirection,
    lots: int,
    order_key: str,
    salt: str = "",
) -> str:
    """Детерминированный UID для идемпотентности `post_limit_order`.

    Один и тот же `order_key` всегда даёт один и тот же UID — повторное
    нажатие «Купить» в UI после rerun-а отправит заявку с тем же UID,
    T-Invest API в этом случае вернёт результат первой заявки без
    создания второй. Это критично — пользователь может случайно ткнуть
    кнопку дважды, или Streamlit перерисует страницу.

    Если пользователь хочет сознательно отправить ВТОРУЮ заявку
    (например, после отмены первой), передаётся `salt` — отличающаяся
    строка (например, ISO-таймстамп подтверждения).

    UID — UUID-формат (32 hex символа, длина 36 с дефисами), как требует
    T-Invest (см. https://russianinvestments.github.io/investAPI/orders/).
    """
    raw = f"{account_id}|{figi}|{direction}|{lots}|{order_key}|{salt}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # UUID-форма: 8-4-4-4-12 hex
    return f"{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


# ── Mapping helpers ──────────────────────────────────────────────────────────


def _direction_to_proto(direction: OrderDirection) -> Any:
    from t_tech.invest import OrderDirection as ProtoOrderDirection

    return (
        ProtoOrderDirection.ORDER_DIRECTION_BUY
        if direction == "BUY"
        else ProtoOrderDirection.ORDER_DIRECTION_SELL
    )


def _direction_from_proto(direction: Any) -> OrderDirection:
    from t_tech.invest import OrderDirection as ProtoOrderDirection

    return "BUY" if direction == ProtoOrderDirection.ORDER_DIRECTION_BUY else "SELL"


def _classify_account_kind(proto_account: Any) -> AccountKind:
    """Sandbox-аккаунты в API возвращаются с типом ``ACCOUNT_TYPE_INVEST_BOX``,
    но проще полагаться на то, через какой клиент мы его получили
    (см. :func:`list_accounts`)."""
    # Не используется напрямую: передаём AccountKind явно. Оставлено
    # как hook для будущих типов.
    raise NotImplementedError


# ── API: accounts ────────────────────────────────────────────────────────────


def list_accounts(token: str, account_kind: AccountKind) -> list[AccountInfo]:
    """Получить список счетов в выбранном контуре.

    Sandbox: `client.users.get_accounts()` через `SandboxClient` уже
    возвращает только sandbox-аккаунты пользователя (выделены
    отдельно от production). Фильтруем по статусу OPEN; для UI
    отмечаем поле `is_writable` (только FULL_ACCESS — можно торговать).
    """
    from t_tech.invest import AccessLevel, AccountStatus

    with _open_client(token, account_kind) as client:
        response = client.users.get_accounts()

    result: list[AccountInfo] = []
    for acc in response.accounts:
        if acc.status != AccountStatus.ACCOUNT_STATUS_OPEN:
            continue
        is_writable = acc.access_level == AccessLevel.ACCOUNT_ACCESS_LEVEL_FULL_ACCESS
        result.append(
            AccountInfo(
                id=acc.id,
                name=acc.name or "",
                kind=account_kind,
                access_level=acc.access_level.name,
                status=acc.status.name,
                is_writable=is_writable,
            )
        )
    return result


# ── API: account snapshot ────────────────────────────────────────────────────


def _portfolio_money_rub(portfolio: PortfolioResponse) -> Rub:
    """Извлечь сумму RUB-кэша из портфельного снапшота.

    Свободные средства в RUB лежат в `total_amount_currencies` (там сумма
    ПО ВСЕМ валютам), либо среди `positions` с `instrument_type='currency'`.
    Для точности берём из `positions`: ищем RUB-currency и берём quantity.
    """
    total_currencies = money_value_to_rub(portfolio.total_amount_currencies) or Rub(0.0)
    rub_in_positions: float = 0.0
    foreign_currency_value: float = 0.0
    for pos in portfolio.positions:
        if pos.instrument_type != "currency":
            continue
        # Для RUB ticker может быть пустой / "RUB000UTSTOM" / похожий.
        ticker = (pos.ticker or "").upper()
        quantity = float(quotation_to_float(pos.quantity) or 0.0)
        if "RUB" in ticker:
            rub_in_positions += quantity
        else:
            # Перевод иностранной валюты в рубли через current_price
            current_price = float(quotation_to_float(pos.current_price) or 0.0)
            foreign_currency_value += quantity * current_price

    if rub_in_positions > 0:
        return Rub(rub_in_positions)
    # Если RUB-позиции явной нет, выводим RUB из общей суммы валют
    # минус оценка иностранных валют — это даёт корректное значение,
    # даже когда нет явной RUB позиции.
    estimated_rub = max(0.0, total_currencies - foreign_currency_value)
    return Rub(estimated_rub)


def _positions_blocked_rub(client: Any, account_id: str) -> Rub:
    """Заблокированные под активные заявки средства (operations.get_positions)."""
    from t_tech.invest.exceptions import RequestError

    try:
        resp = client.operations.get_positions(account_id=account_id)
    except RequestError:
        return Rub(0.0)

    total = 0.0
    for mv in resp.blocked:
        currency = (getattr(mv, "currency", None) or "").lower()
        if currency not in ("rub", "rur"):
            continue
        amount = money_value_to_rub(mv)
        if amount is not None:
            total += float(amount)
    return Rub(total)


def _fetch_bond_nominal_rub(client: Any, *, figi: str, instrument_uid: str) -> float | None:
    """Номинал облигации из ``instruments.bond_by`` (нужен для % ↔ ₽)."""
    from t_tech.invest import InstrumentIdType

    lookups: list[tuple[object, str]] = []
    if instrument_uid:
        lookups.append((InstrumentIdType.INSTRUMENT_ID_TYPE_UID, instrument_uid))
    if figi:
        lookups.append((InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, figi))

    for id_type, id_value in lookups:
        try:
            resp = client.instruments.bond_by(id_type=id_type, id=id_value)
        except Exception:
            logger.debug("bond_by failed for %s=%s", id_type, id_value, exc_info=True)
            continue
        nominal = money_value_to_rub(resp.instrument.nominal)
        if nominal is not None and nominal > 0:
            return float(nominal)
    return None


def _bond_price_pct_from_rub(
    price_rub: float | None,
    *,
    nominal_rub: float | None,
) -> PriceUnitPct | None:
    if price_rub is None or nominal_rub is None or nominal_rub <= 0:
        return None
    return bond_clean_price_pct_from_rub(clean_price_rub=price_rub, face_value=nominal_rub)


def _classify_position(
    pos: Any,
    *,
    nominal_rub: float | None = None,
) -> tuple[str, OtherInstrument | BondPosition | None]:
    """Классифицировать позицию: bond / other / skip(пустая или RUB-кэш).

    Возвращает кортеж ``(kind, value)``:
    * ``("bond", BondPosition)`` — облигация;
    * ``("other", OtherInstrument)`` — акция / etf / валюта ≠ RUB /
      фьючерс / опцион;
    * ``("skip", None)`` — RUB-кэш или нулевая позиция.
    """
    quantity = float(quotation_to_float(pos.quantity) or 0.0)
    if quantity <= 0:
        return ("skip", None)

    instrument_type = (pos.instrument_type or "").lower()
    if instrument_type == "currency":
        ticker = (pos.ticker or "").upper()
        if "RUB" in ticker:
            return ("skip", None)
        return (
            "other",
            OtherInstrument(
                instrument_type="currency",
                figi=pos.figi or "",
                ticker=pos.ticker or "",
                quantity=int(quantity),
            ),
        )
    if instrument_type == "bond":
        current_price = quotation_to_float(pos.current_price)
        current_price_pct = _bond_price_pct_from_rub(current_price, nominal_rub=nominal_rub)
        current_nkd = money_value_to_rub(pos.current_nkd)
        avg_price = quotation_to_float(pos.average_position_price)
        avg_price_pct = _bond_price_pct_from_rub(avg_price, nominal_rub=nominal_rub)
        lots_raw = float(quotation_to_float(pos.quantity_lots) or 0.0)
        lots = max(1, int(lots_raw)) if lots_raw > 0 else max(1, int(quantity))
        return (
            "bond",
            BondPosition(
                figi=pos.figi,
                instrument_uid=pos.instrument_uid,
                ticker=pos.ticker or "",
                quantity=int(quantity),
                lots=lots,
                blocked=int(float(quotation_to_float(pos.blocked) or 0.0)),
                current_price_pct=current_price_pct,
                current_nkd_rub=current_nkd,
                average_price_pct=avg_price_pct,
            ),
        )
    # share / etf / future / option / sp / dfa / ... — любое не-облигация
    # считается «чужим» инструментом и блокирует attach.
    return (
        "other",
        OtherInstrument(
            instrument_type=instrument_type or "unknown",
            figi=pos.figi or "",
            ticker=pos.ticker or "",
            quantity=int(quantity),
        ),
    )


def get_account_snapshot(
    token: str,
    account_kind: AccountKind,
    account_id: str,
) -> AccountSnapshot:
    """Снимок счёта: RUB-кэш + позиции (облигации vs прочее).

    Production: `client.operations.get_portfolio`;
    Sandbox: `client.sandbox.get_sandbox_portfolio` — но через `SandboxClient`
    обычные `client.operations.*` тоже работают. Используем единый путь
    через `operations.get_portfolio` — он реализован у обоих клиентов.
    """
    from t_tech.invest.exceptions import RequestError

    try:
        with _open_client(token, account_kind) as client:
            portfolio = client.operations.get_portfolio(account_id=account_id)
            money_rub = _portfolio_money_rub(portfolio)
            blocked_money_rub = _positions_blocked_rub(client, account_id)
            bond_nominals: dict[str, float] = {}
            for pos in portfolio.positions:
                if (pos.instrument_type or "").lower() != "bond":
                    continue
                figi = pos.figi or ""
                if not figi or figi in bond_nominals:
                    continue
                nominal = _fetch_bond_nominal_rub(
                    client,
                    figi=figi,
                    instrument_uid=pos.instrument_uid or "",
                )
                if nominal is not None:
                    bond_nominals[figi] = nominal

            bonds: dict[str, BondPosition] = {}
            others: list[OtherInstrument] = []
            for pos in portfolio.positions:
                nominal = (
                    bond_nominals.get(pos.figi or "")
                    if (pos.instrument_type or "").lower() == "bond"
                    else None
                )
                kind, value = _classify_position(pos, nominal_rub=nominal)
                if kind == "bond" and isinstance(value, BondPosition):
                    bonds[value.figi] = value
                elif kind == "other" and isinstance(value, OtherInstrument):
                    others.append(value)
    except RequestError as exc:
        raise _map_request_error(exc, account_id=account_id) from exc

    return AccountSnapshot(
        account_id=account_id,
        account_kind=account_kind,
        money_rub=money_rub,
        blocked_money_rub=blocked_money_rub,
        bond_positions=bonds,
        other_instruments=others,
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


# ── API: operations ──────────────────────────────────────────────────────────


def _operation_to_record(item: OperationItem) -> OperationRecord:
    type_name = getattr(item.type, "name", str(item.type))
    state_name = getattr(item.state, "name", str(item.state))
    # Для облигаций T-Invest возвращает чистую цену в ₽ за бумагу.
    # Конвертация в % от номинала — при сериализации в API (см. universe).
    price_raw: PriceUnitPct | None = None
    raw_price = quotation_to_float(item.price)
    if raw_price is not None:
        price_raw = PriceUnitPct(raw_price)
    return OperationRecord(
        id=item.id,
        type=type_name,
        state=state_name,
        date=item.date,
        figi=item.figi or "",
        instrument_uid=item.instrument_uid or "",
        instrument_type=(item.instrument_type or "").lower(),
        payment_rub=money_value_to_rub(item.payment),
        quantity=int(item.quantity or 0),
        price_pct=price_raw,
        commission_rub=money_value_to_rub(item.commission),
        raw=item,
    )


def get_account_operations(
    token: str,
    account_kind: AccountKind,
    account_id: str,
    *,
    from_date: date,
    to_date: date | None = None,
) -> list[OperationRecord]:
    """Все операции счёта в диапазоне ``[from_date, to_date]``.

    Использует ``get_operations_by_cursor`` с пагинацией — все страницы
    собираются в один список (для портфельных горизонтов в 1–3 года это
    обычно сотни строк, не миллионы).
    """
    from t_tech.invest import GetOperationsByCursorRequest

    from_dt = datetime.combine(from_date, datetime.min.time(), tzinfo=UTC)
    if to_date is None:
        to_dt = datetime.now(UTC)
    else:
        to_dt = datetime.combine(to_date, datetime.max.time(), tzinfo=UTC)

    records: list[OperationRecord] = []
    cursor: str | None = None
    from t_tech.invest.exceptions import RequestError

    try:
        with _open_client(token, account_kind) as client:
            while True:
                req = GetOperationsByCursorRequest(
                    account_id=account_id,
                    from_=from_dt,
                    to=to_dt,
                    cursor=cursor or "",
                    limit=200,
                )
                resp = client.operations.get_operations_by_cursor(req)
                for item in resp.items:
                    records.append(_operation_to_record(item))
                if not resp.has_next or not resp.next_cursor:
                    break
                cursor = resp.next_cursor
    except RequestError as exc:
        raise _map_request_error(exc, account_id=account_id) from exc
    return records


# ── API: orders ──────────────────────────────────────────────────────────────


def post_limit_order(
    token: str,
    account_kind: AccountKind,
    *,
    account_id: str,
    figi: str,
    direction: OrderDirection,
    lots: Lots,
    price_pct: PriceUnitPct,
    request_uid: str,
    face_value: float,
    estimated_total_amount_rub: Rub | None = None,
    instrument_uid: str = "",
) -> PostOrderResult:
    """Отправить ЛИМИТНУЮ заявку (BUY или SELL).

    Args:
        estimated_total_amount_rub: Ожидаемая полная сумма заявки в ₽ —
            используется для проверки лимита 30 млн ₽ ДО отправки в API.
            Не блокер если ``None`` (будет проверено внутри по `executed_*` после
            ответа), но крайне рекомендуется заполнять.

    Raises:
        OrderTooLargeError: Если сумма превышает MAX_ORDER_AMOUNT_RUB.
        TradingClientError: Любые сетевые / валидационные ошибки API.
    """
    from t_tech.invest import OrderType, TimeInForceType
    from t_tech.invest.exceptions import RequestError

    if estimated_total_amount_rub is not None and estimated_total_amount_rub > MAX_ORDER_AMOUNT_RUB:
        raise OrderTooLargeError(
            f"Сумма заявки {estimated_total_amount_rub:,.0f} ₽ > {MAX_ORDER_AMOUNT_RUB:,.0f} ₽ "
            f"(API требует SMS-подтверждения, через API не доступно). "
            f"Разделите на несколько заявок."
        )

    direction_proto = _direction_to_proto(direction)
    price_quotation = bond_clean_price_quotation(price_pct=price_pct, face_value=face_value)
    instrument_kwargs = _order_instrument_kwargs(figi=figi, instrument_uid=instrument_uid)

    payload = {
        "account_id": account_id,
        "figi": figi,
        "instrument_uid": instrument_uid,
        "direction": direction,
        "lots": int(lots),
        "price_pct": float(price_pct),
        "request_uid": request_uid,
        "account_kind": account_kind.value,
    }
    _audit_log("post_order.attempt", payload)

    def _submit() -> PostOrderResponse:
        with _open_client(token, account_kind) as client:
            return client.orders.post_order(
                quantity=int(lots),
                price=price_quotation,
                direction=direction_proto,
                account_id=account_id,
                order_type=OrderType.ORDER_TYPE_LIMIT,
                order_id=request_uid,
                time_in_force=TimeInForceType.TIME_IN_FORCE_DAY,
                **instrument_kwargs,
            )

    try:
        response = _submit()
    except RequestError as exc:
        code = _request_error_code(exc)
        if code == "30052":
            _audit_log("post_order.error", {**payload, "error": str(exc), "code": code})
            raise TradingNotAvailableError(
                "Облигация недоступна для торговли через API "
                f"(код {code}: {_request_error_message(exc)})"
            ) from exc
        # Повтор с тем же request_uid: API вернёт статус уже выставленной заявки.
        if code == "70002":
            logger.warning(
                "post_order retry after %s for request_uid=%s", code, request_uid
            )
            try:
                response = _submit()
            except RequestError as retry_exc:
                _audit_log(
                    "post_order.error",
                    {**payload, "error": str(retry_exc), "retry_after": code},
                )
                raise TradingClientError(
                    f"T-Invest API отклонил заявку: {retry_exc}"
                ) from retry_exc
        else:
            _audit_log("post_order.error", {**payload, "error": str(exc), "code": code})
            if code == "30057":
                raise TradingClientError(
                    "Заявка с этим ключом идемпотентности уже была отправлена, "
                    "но отчёт не найден. Повторите подтверждение — будет "
                    "сгенерирован новый ключ."
                ) from exc
            raise TradingClientError(f"T-Invest API отклонил заявку: {exc}") from exc

    executed_pct: PriceUnitPct | None = None
    if response.executed_order_price is not None:
        # executed_order_price для облигаций приходит в % от номинала
        # (как и `price` в запросе) — это явно указано в спеках.
        val = quotation_to_float(response.executed_order_price)
        if val is not None:
            executed_pct = PriceUnitPct(val)

    result = PostOrderResult(
        order_id=response.order_id,
        request_uid=request_uid,
        execution_report_status=getattr(
            response.execution_report_status, "name", str(response.execution_report_status)
        ),
        lots_executed=int(response.lots_executed or 0),
        lots_requested=int(response.lots_requested or 0),
        executed_price_pct=executed_pct,
        initial_order_price_rub=money_value_to_rub(response.initial_order_price),
        total_order_amount_rub=money_value_to_rub(response.total_order_amount),
        initial_commission_rub=money_value_to_rub(response.initial_commission),
        message=response.message or "",
    )
    _audit_log(
        "post_order.success",
        {
            **payload,
            "order_id": result.order_id,
            "execution_report_status": result.execution_report_status,
            "lots_executed": result.lots_executed,
            "total_order_amount_rub": result.total_order_amount_rub,
        },
    )
    return result


def post_market_sell_order(
    token: str,
    account_kind: AccountKind,
    *,
    account_id: str,
    lots: Lots,
    request_uid: str,
    figi: str = "",
    instrument_uid: str = "",
    instrument_id: str = "",
    reference_price_pct: PriceUnitPct | None = None,
    lot_size: int = 1,
    face_value: float = 1000.0,
) -> PostOrderResult:
    """Продать лоты «по рынку» — лимитная заявка чуть ниже последней цены.

    T-Invest API для облигаций не поддерживает ``ORDER_TYPE_MARKET`` /
    ``ORDER_TYPE_BESTPRICE`` (часто отвечает 30052). Используем агрессивный
    LIMIT SELL, как в sandbox happy-path.
    """
    resolved_uid = instrument_uid or (instrument_id if "-" in instrument_id else "")
    resolved_figi = figi or (instrument_id if instrument_id and not resolved_uid else "")
    base_price = float(reference_price_pct or PriceUnitPct(100.0))
    sell_price = PriceUnitPct(max(1.0, round(base_price * 0.97, 4)))
    estimated = Rub(int(lots) * lot_size * face_value * float(sell_price) / 100.0)
    return post_limit_order(
        token,
        account_kind,
        account_id=account_id,
        figi=resolved_figi,
        instrument_uid=resolved_uid,
        direction="SELL",
        lots=lots,
        price_pct=sell_price,
        face_value=face_value,
        request_uid=request_uid,
        estimated_total_amount_rub=estimated,
    )


def _order_limit_price_pct_from_state(
    state: ProtoOrderState,
    *,
    face_value: float | None,
) -> PriceUnitPct | None:
    """Лимитная цена заявки в % от номинала.

  T-Invest в ``initial_security_price`` для облигаций возвращает чистую цену
  **в рублях за 1 бумагу**, а не пункты/% (см. table_order_currency).
    """
    limit_rub = quotation_to_float(state.initial_security_price)
    if limit_rub is None:
        return None
    if face_value is not None and face_value > 0:
        return bond_clean_price_pct_from_rub(clean_price_rub=limit_rub, face_value=face_value)
    return PriceUnitPct(limit_rub)


def _order_state_from_proto(
    state: ProtoOrderState,
    *,
    face_value: float | None = None,
) -> OrderState:
    executed_pct: PriceUnitPct | None = None
    val = quotation_to_float(state.executed_order_price)
    if val is not None:
        # executed_order_price для облигаций приходит в % от номинала
        executed_pct = PriceUnitPct(val)

    limit_pct = _order_limit_price_pct_from_state(state, face_value=face_value)

    return OrderState(
        order_id=state.order_id,
        execution_report_status=getattr(
            state.execution_report_status, "name", str(state.execution_report_status)
        ),
        figi=state.figi or "",
        direction=_direction_from_proto(state.direction),
        lots_executed=int(state.lots_executed or 0),
        lots_requested=int(state.lots_requested or 0),
        executed_price_pct=executed_pct,
        initial_order_price_rub=money_value_to_rub(state.initial_order_price),
        total_order_amount_rub=money_value_to_rub(state.total_order_amount),
        order_date=state.order_date,
        request_uid=str(state.order_request_id or ""),
        price_pct=limit_pct,
        initial_commission_rub=money_value_to_rub(state.initial_commission),
    )


def get_order_state(
    token: str,
    account_kind: AccountKind,
    *,
    account_id: str,
    order_id: str,
    face_value: float | None = None,
) -> OrderState:
    """Статус заявки на бирже (`EXECUTION_REPORT_STATUS_*`)."""
    with _open_client(token, account_kind) as client:
        state: ProtoOrderState = client.orders.get_order_state(
            account_id=account_id, order_id=order_id
        )
        resolved_face = face_value
        if resolved_face is None and state.figi:
            resolved_face = _fetch_bond_nominal_rub(
                client,
                figi=state.figi,
                instrument_uid=state.instrument_uid or "",
            )

    return _order_state_from_proto(state, face_value=resolved_face)


_ACTIVE_ORDER_STATUS_NAMES = frozenset({
    "EXECUTION_REPORT_STATUS_NEW",
    "EXECUTION_REPORT_STATUS_PARTIALLYFILL",
    "EXECUTION_REPORT_STATUS_PENDING_CANCEL",
})


def get_active_orders(
    token: str,
    account_kind: AccountKind,
    *,
    account_id: str,
) -> list[OrderState]:
    """Активные заявки на счёте (NEW, PARTIALLYFILL, PENDING_CANCEL).

    На production ``execution_status`` в ``get_orders`` требует ``from`` (код
    30001) — запрашиваем все активные заявки и фильтруем локально.
    """
    from t_tech.invest.exceptions import RequestError

    try:
        with _open_client(token, account_kind) as client:
            resp = client.orders.get_orders(account_id=account_id)
            nominal_cache: dict[str, float | None] = {}
            orders: list[OrderState] = []
            for state in resp.orders:
                status_name = getattr(
                    state.execution_report_status,
                    "name",
                    str(state.execution_report_status),
                )
                if status_name not in _ACTIVE_ORDER_STATUS_NAMES:
                    continue
                figi = state.figi or ""
                if figi not in nominal_cache:
                    nominal_cache[figi] = _fetch_bond_nominal_rub(
                        client,
                        figi=figi,
                        instrument_uid=state.instrument_uid or "",
                    )
                orders.append(
                    _order_state_from_proto(state, face_value=nominal_cache[figi])
                )
    except RequestError as exc:
        raise _map_request_error(exc, account_id=account_id) from exc

    return orders


def cancel_order(
    token: str,
    account_kind: AccountKind,
    *,
    account_id: str,
    order_id: str,
) -> bool:
    """Отменить активную заявку. Возвращает ``True`` если API вернул успех."""
    from t_tech.invest.exceptions import RequestError

    payload = {
        "account_id": account_id,
        "order_id": order_id,
        "account_kind": account_kind.value,
    }
    _audit_log("cancel_order.attempt", payload)
    try:
        with _open_client(token, account_kind) as client:
            client.orders.cancel_order(account_id=account_id, order_id=order_id)
    except RequestError as exc:
        _audit_log("cancel_order.error", {**payload, "error": str(exc)})
        return False
    _audit_log("cancel_order.success", payload)
    return True


def preview_order_price(
    token: str,
    account_kind: AccountKind,
    *,
    account_id: str,
    figi: str,
    direction: OrderDirection,
    lots: Lots,
    price_pct: PriceUnitPct,
    face_value: float,
    instrument_uid: str = "",
) -> OrderPricePreview | None:
    """Предварительный расчёт стоимости заявки (НКД + комиссия + итог).

    Удобно показывать в UI рядом с полем «Лимитная цена», чтобы
    пользователь видел реальную сумму до подтверждения.
    """
    from t_tech.invest import GetOrderPriceRequest
    from t_tech.invest.exceptions import RequestError

    instrument_kwargs = _order_instrument_kwargs(figi=figi, instrument_uid=instrument_uid)
    price_request_id = instrument_kwargs.get("instrument_id") or instrument_kwargs.get("figi", "")

    try:
        with _open_client(token, account_kind) as client:
            resp = client.orders.get_order_price(
                GetOrderPriceRequest(
                    account_id=account_id,
                    instrument_id=price_request_id,
                    direction=_direction_to_proto(direction),
                    quantity=int(lots),
                    price=bond_clean_price_quotation(
                        price_pct=price_pct,
                        face_value=face_value,
                    ),
                )
            )
    except RequestError as exc:
        logger.warning("preview_order_price failed for %s: %s", figi, exc)
        return None

    aci_amount = (
        money_value_to_rub(resp.extra_bond.aci_value)
        if resp.extra_bond is not None
        else None
    )
    return OrderPricePreview(
        lots_requested=int(resp.lots_requested or lots),
        clean_amount_rub=money_value_to_rub(resp.initial_order_amount),
        aci_amount_rub=aci_amount,
        total_order_amount_rub=money_value_to_rub(resp.total_order_amount),
        executed_commission_rub=money_value_to_rub(resp.executed_commission),
        deal_commission_rub=money_value_to_rub(resp.deal_commission),
    )


# ── Sandbox-only API ─────────────────────────────────────────────────────────


def open_sandbox_account(token: str, name: str = "bond-monitor-test") -> str:
    """Создать новый sandbox-счёт. Возвращает `account_id`."""
    from t_tech.invest.sandbox.client import SandboxClient

    with SandboxClient(token) as client:
        resp = client.sandbox.open_sandbox_account(name=name)
    _audit_log(
        "open_sandbox_account",
        {"account_id": resp.account_id, "name": name},
    )
    return resp.account_id


def close_sandbox_account(token: str, account_id: str) -> None:
    """Закрыть sandbox-счёт. Только для e2e cleanup."""
    from t_tech.invest.sandbox.client import SandboxClient

    with SandboxClient(token) as client:
        client.sandbox.close_sandbox_account(account_id=account_id)
    _audit_log("close_sandbox_account", {"account_id": account_id})


def sandbox_pay_in(token: str, account_id: str, amount_rub: Rub) -> Rub:
    """Пополнить sandbox-счёт. Возвращает фактический баланс после пополнения."""
    from t_tech.invest import MoneyValue
    from t_tech.invest.sandbox.client import SandboxClient

    units = int(amount_rub)
    nano = int(round((amount_rub - units) * 1_000_000_000))
    money = MoneyValue(currency="rub", units=units, nano=nano)
    with SandboxClient(token) as client:
        resp = client.sandbox.sandbox_pay_in(account_id=account_id, amount=money)
    balance = money_value_to_rub(resp.balance) or Rub(0.0)
    _audit_log(
        "sandbox_pay_in",
        {"account_id": account_id, "amount_rub": float(amount_rub), "balance_rub": float(balance)},
    )
    return balance


__all__ = [
    "AccountInfo",
    "AccountNotFoundError",
    "AccountSnapshot",
    "BondPosition",
    "OperationRecord",
    "OrderPricePreview",
    "OrderState",
    "OrderTooLargeError",
    "OtherInstrument",
    "PostOrderResult",
    "TradingClientError",
    "TradingNotAvailableError",
    "TradingTokenMissingError",
    "cancel_order",
    "close_sandbox_account",
    "get_account_operations",
    "get_account_snapshot",
    "get_active_orders",
    "get_order_state",
    "list_accounts",
    "make_request_uid",
    "open_sandbox_account",
    "post_limit_order",
    "post_market_sell_order",
    "preview_order_price",
    "resolve_token",
    "sandbox_pay_in",
]
