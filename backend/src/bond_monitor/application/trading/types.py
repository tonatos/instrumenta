"""Shared DTOs for trading application layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrderPreviewResult:
    """Превью стоимости заявки до подтверждения."""

    order_lots: int
    order_bonds: int
    lot_size: int
    order_price_pct: float
    clean_amount_rub: float
    aci_rub_per_bond: float
    local_total_amount_rub: float
    broker_clean_amount_rub: float | None
    broker_aci_amount_rub: float | None
    broker_total_amount_rub: float | None
    broker_commission_rub: float | None
    money_rub: float
    sufficient_cash: bool
    preview_source: str = "moex"
    market_price_pct: float | None = None
    face_value_rub: float = 1000.0


@dataclass
class SellPositionPreviewResult(OrderPreviewResult):
    """Превью прямой продажи позиции."""

    available_lots: int = 0
    sufficient_lots: bool = False
    suggested_price_pct: float | None = None


@dataclass
class SellQuoteResult:
    """Рекомендуемая лимитная цена продажи и рыночная база."""

    market_price_pct: float
    suggested_price_pct: float
    available_lots: int
    sell_buffer_label: str


@dataclass
class PlaceOrderResult:
    """Результат отправки заявки на биржу."""

    order_id: str
    status: str
    request_uid: str
    lots_requested: int
    lots_executed: int
    total_order_amount_rub: float | None = None
    initial_commission_rub: float | None = None


@dataclass
class HoldingResponse:
    figi: str
    isin: str
    name: str
    lots: int
    quantity: int
    lot_size: int
    current_price_pct: float | None
    current_nkd_rub: float | None
    ytm: float | None
    maturity_date: str | None
    offer_date: str | None
    market_value_rub: float | None


@dataclass
class SuggestionResponse:
    id: str
    kind: str
    isin: str
    name: str
    lots: int
    figi: str | None
    suggested_price_pct: float | None
    reason: str
    market_price_pct: float | None = None
    due_date: str | None = None
    source_isin: str | None = None
    chat_template: str | None = None
    urgency: str = "normal"
    risk_acknowledgeable: bool = False
    offer_window_status: str | None = None
    submission_start: str | None = None
    submission_end: str | None = None


@dataclass
class ActiveOrderResponse:
    order_id: str
    request_uid: str
    figi: str
    direction: str
    lots_requested: int
    lots_executed: int
    status: str
    price_pct: float | None = None
    total_order_amount_rub: float | None = None
    initial_commission_rub: float | None = None


@dataclass
class PerformanceResponse:
    xirr_pct: float | None
    coupons_received_rub: float
    tax_paid_rub: float
    commission_paid_rub: float
    realized_profit_rub: float
    unrealized_value_rub: float
    invested_rub: float
    received_rub: float
    as_of: str


@dataclass
class DeploySessionItemResponse:
    id: str
    kind: str
    isin: str
    name: str
    lots: int
    figi: str | None
    suggested_price_pct: float
    estimated_amount_rub: float
    reason: str
    status: str
    source_isin: str | None = None
    due_date: str | None = None
    order_id: str | None = None
    urgency: str = "normal"


@dataclass
class DeploySessionProgressResponse:
    total: int
    pending: int
    placed: int
    filled: int
    skipped: int
    stale: int


@dataclass
class DeploySessionResponse:
    id: str
    status: str
    expires_at: str
    cash_snapshot_rub: float
    progress: DeploySessionProgressResponse
    items: list[DeploySessionItemResponse]
    warnings: list[str] = field(default_factory=list)


@dataclass
class TradingAdviceResult:
    """Результат stateless advisory."""

    holdings: list[HoldingResponse]
    cashflow: list[dict]
    performance: PerformanceResponse | None
    suggestions: list[SuggestionResponse]
    active_orders: list[ActiveOrderResponse]
    money_rub: float
    available_money_rub: float
    blocked_money_rub: float
    warnings: list[str] = field(default_factory=list)
    as_of: str = ""
    weighted_duration_years: float | None = None
    deploy_session: DeploySessionResponse | None = None
