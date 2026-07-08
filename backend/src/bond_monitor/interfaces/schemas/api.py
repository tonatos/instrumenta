"""Pydantic schemas for API request/response DTOs."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ConfigResponse(BaseModel):
    key_rate: float
    tax_rate: float
    max_days: int
    min_volume_rub: float
    tinkoff_configured: bool
    sandbox_configured: bool
    production_configured: bool


class ConfigUpdateRequest(BaseModel):
    key_rate: float | None = None
    tax_rate: float | None = None
    max_days: int | None = None
    min_volume_rub: float | None = None


class BondResponse(BaseModel):
    secid: str
    isin: str
    name: str
    figi: str = ""
    maturity_date: date | None = None
    offer_date: date | None = None
    call_date: date | None = None
    effective_date: date | None = None
    days_to_maturity: int | None = None
    ytm: float | None = None
    ytm_net: float | None = None
    coupon_rate: float | None = None
    coupon_type: str = "unknown"
    last_price: float | None = None
    face_value: float = 1000.0
    lot_size: int = 1
    volume_rub: float | None = None
    prev_volume_rub: float | None = None
    credit_rating: str | None = None
    risk_level: int = 0
    score: float | None = None
    ytm_score: float | None = None
    risk_score: float | None = None
    liquidity_score: float | None = None
    is_favorite: bool = False
    has_warnings: bool = False
    warnings: list[str] = Field(default_factory=list)
    tinvest_enriched: bool = False
    issuer_name: str = ""
    instrument_full_name: str = ""
    sector: str = ""
    description: str = ""


class BondsListResponse(BaseModel):
    bonds: list[BondResponse]
    source: str
    count: int


class CreatePortfolioRequest(BaseModel):
    name: str
    initial_amount_rub: float
    horizon_date: date
    risk_profile: str = "normal"
    api_trade_only: bool = True


class PortfolioPositionData(BaseModel):
    isin: str
    secid: str
    name: str
    lots: int
    lot_size: int
    purchase_clean_price_pct: float
    purchase_dirty_price_rub: float
    purchase_aci_rub: float
    purchase_date: str
    purchase_amount_rub: float
    coupon_rate: float | None = None
    face_value: float
    maturity_date: str | None = None
    offer_date: str | None = None
    offer_submission_start: str | None = None
    offer_submission_end: str | None = None
    offer_price_pct: float | None = None
    coupon_period_days: int | None = None
    next_coupon_date: str | None = None
    source: str
    figi: str | None = None
    status: str | None = None


class ReinvestmentSlotData(BaseModel):
    trigger_date: str
    trigger_reason: str
    expected_cash_rub: float
    suggested_isin: str | None = None
    suggested_name: str | None = None
    confirmed_isin: str | None = None
    gap_days: int = 2
    source_position_isin: str | None = None


class FrozenForecastData(BaseModel):
    expected_xirr_pct: float | None
    expected_total_net_profit_rub: float
    expected_final_value_rub: float
    frozen_initial_amount_rub: float
    horizon_date: str
    created_at: str


class PortfolioDataResponse(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    initial_amount_rub: float
    horizon_date: str
    risk_profile: str
    api_trade_only: bool = True
    cash_balance_rub: float
    mode: str
    account_id: str | None = None
    account_kind: str | None = None
    account_label: str | None = None
    trading_started_at: str | None = None
    frozen_forecast: FrozenForecastData | None = None
    positions: list[PortfolioPositionData] = Field(default_factory=list)
    slots: list[ReinvestmentSlotData] = Field(default_factory=list)
    closed_positions_count: int = 0


class PortfolioResponse(BaseModel):
    id: str
    name: str
    initial_amount_rub: float
    horizon_date: date
    risk_profile: str
    cash_balance_rub: float
    mode: str
    account_id: str | None = None
    account_kind: str | None = None
    positions_count: int
    closed_positions_count: int = 0
    invested_capital_rub: float
    data: PortfolioDataResponse


class PlanResponse(BaseModel):
    total_net_profit_rub: float
    total_net_profit_with_held_rub: float
    invested_capital_rub: float
    total_invested_rub: float
    final_cash_balance: float
    final_portfolio_value: float
    expected_xirr_pct: float | None = None
    notes: list[str] = Field(default_factory=list)
    cashflow: list[dict[str, Any]] = Field(default_factory=list)
    value_timeline: list[dict[str, Any]] = Field(default_factory=list)
    held_positions: list[dict[str, Any]] = Field(default_factory=list)
    slots: list[dict[str, Any]] = Field(default_factory=list)


class UpdatePortfolioRequest(BaseModel):
    name: str | None = None
    initial_amount_rub: float | None = None
    horizon_date: date | None = None
    risk_profile: str | None = None
    api_trade_only: bool | None = None


class AddPositionRequest(BaseModel):
    isin: str
    lots: int = Field(ge=1)


class SetSlotOverrideRequest(BaseModel):
    source_position_isin: str
    confirmed_isin: str | None = None


class CalculatorRequest(BaseModel):
    secids: list[str]
    budget_rub: float


class CalculatorResponse(BaseModel):
    results: list[dict[str, Any]]
    total_invested_rub: float
    total_profit_rub: float
    portfolio_yield_pct: float | None = None


class PositionDriftResponse(BaseModel):
    isin: str
    name: str
    expected_lots: int
    actual_lots: int
    severity: str
    message: str


class HoldingResponse(BaseModel):
    figi: str
    isin: str
    name: str
    lots: int
    quantity: int
    lot_size: int
    current_price_pct: float | None = None
    current_nkd_rub: float | None = None
    ytm: float | None = None
    maturity_date: str | None = None
    offer_date: str | None = None
    market_value_rub: float | None = None


class SuggestionResponse(BaseModel):
    id: str
    kind: str
    isin: str
    name: str
    lots: int
    figi: str | None = None
    suggested_price_pct: float | None = None
    market_price_pct: float | None = None
    reason: str = ""
    due_date: str | None = None
    source_isin: str | None = None
    chat_template: str | None = None
    urgency: str = "normal"


class ActiveOrderResponse(BaseModel):
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


class PerformanceDataResponse(BaseModel):
    xirr_pct: float | None = None
    coupons_received_rub: float = 0.0
    tax_paid_rub: float = 0.0
    commission_paid_rub: float = 0.0
    realized_profit_rub: float = 0.0
    unrealized_value_rub: float = 0.0
    invested_rub: float = 0.0
    received_rub: float = 0.0
    as_of: str = ""


class TradingAdviceResponse(BaseModel):
    holdings: list[HoldingResponse] = Field(default_factory=list)
    cashflow: list[dict[str, Any]] = Field(default_factory=list)
    performance: PerformanceDataResponse | None = None
    suggestions: list[SuggestionResponse] = Field(default_factory=list)
    active_orders: list[ActiveOrderResponse] = Field(default_factory=list)
    money_rub: float
    available_money_rub: float = 0.0
    blocked_money_rub: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    as_of: str = ""


class PlaceOrderRequest(BaseModel):
    isin: str
    direction: str = Field(pattern="^(BUY|SELL)$")
    lots: int = Field(ge=1)
    price_pct: float = Field(gt=0)
    figi: str | None = None
    suggestion_id: str | None = None


class PlaceOrderResponse(BaseModel):
    order_id: str
    status: str
    request_uid: str
    lots_requested: int
    lots_executed: int
    total_order_amount_rub: float | None = None
    initial_commission_rub: float | None = None


class OrderPreviewResponse(BaseModel):
    order_lots: int
    order_bonds: int
    lot_size: int
    order_price_pct: float
    clean_amount_rub: float
    aci_rub_per_bond: float
    local_total_amount_rub: float
    broker_clean_amount_rub: float | None = None
    broker_aci_amount_rub: float | None = None
    broker_total_amount_rub: float | None = None
    broker_commission_rub: float | None = None
    money_rub: float
    sufficient_cash: bool
    preview_source: str = "moex"
    market_price_pct: float | None = None
    face_value_rub: float = 1000.0


class SellPositionRequest(BaseModel):
    lots: int = Field(ge=1)
    price_pct: float = Field(gt=0)


class SellQuoteResponse(BaseModel):
    market_price_pct: float
    suggested_price_pct: float
    available_lots: int
    sell_buffer_label: str


class SellPositionPreviewResponse(OrderPreviewResponse):
    available_lots: int
    sufficient_lots: bool
    suggested_price_pct: float | None = None


class AccountBondPositionPreview(BaseModel):
    figi: str
    ticker: str
    quantity: int
    lots: int
    current_price_pct: float | None = None


class AccountOtherInstrumentPreview(BaseModel):
    instrument_type: str
    ticker: str
    figi: str
    quantity: int


class LinkedPortfolioPreview(BaseModel):
    id: str
    name: str


class AccountPreviewResponse(BaseModel):
    money_rub: float
    bond_positions: list[AccountBondPositionPreview] = Field(default_factory=list)
    other_instruments: list[AccountOtherInstrumentPreview] = Field(default_factory=list)
    has_securities: bool = False
    can_attach: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sold_count: int | None = None
    sold: list[dict[str, Any]] | None = None
    account_id: str | None = None
    account_replaced: dict[str, str] | None = None
    reset_note: str | None = None
    linked_portfolio: LinkedPortfolioPreview | None = None


class ClearAccountRequest(BaseModel):
    account_id: str
    kind: str = "sandbox"
    pay_in_rub: float | None = Field(default=None, gt=0)


class CreateSandboxAccountRequest(BaseModel):
    initial_amount_rub: float = Field(gt=0)
    name: str | None = Field(default=None, max_length=120)


class BrokerAccountResponse(BaseModel):
    id: str
    name: str
    kind: str
    money_rub: float | None = None
    linked_portfolio: LinkedPortfolioPreview | None = None


class DeleteSandboxAccountResponse(BaseModel):
    account_id: str
    deleted_portfolio_id: str | None = None


class SandboxPayInRequest(BaseModel):
    amount_rub: float = Field(gt=0)


class SandboxPayInResponse(BaseModel):
    amount_added_rub: float
    money_rub: float


class AccountOperationResponse(BaseModel):
    id: str
    type: str
    type_label: str
    state: str
    state_label: str
    date: str
    figi: str
    instrument_type: str
    isin: str | None = None
    name: str | None = None
    payment_rub: float | None = None
    quantity: int
    price_pct: float | None = None
    commission_rub: float | None = None


class AccountOperationsResponse(BaseModel):
    operations: list[AccountOperationResponse]
