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
    data: dict[str, Any] = Field(default_factory=dict)


class PlanResponse(BaseModel):
    total_net_profit_rub: float
    total_net_profit_with_held_rub: float
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


class PendingOperationResponse(BaseModel):
    id: str
    kind: str
    isin: str
    name: str
    lots: int
    figi: str | None = None
    suggested_price_pct: float | None = None
    due_date: str | None = None
    reason: str = ""
    slot_id: str | None = None
    top_up_batch_id: str | None = None
    submitted_request_uid: str | None = None
    created_at: str | None = None
    status: str = "action_required"
    block_reason: str | None = None
    estimated_amount_rub: float | None = None
    face_value_rub: float | None = None
    lot_size: int | None = None
    aci_rub_per_bond: float | None = None
    active_order_id: str | None = None
    active_order_status: str | None = None
    active_order_lots: int | None = None
    active_order_price_pct: float | None = None
    active_order_total_rub: float | None = None
    active_order_commission_rub: float | None = None
    active_order_lots_executed: int | None = None
    active_order_bonds_count: int | None = None
    urgency: str = "normal"
    chat_template: str | None = None


class TradingSyncResponse(BaseModel):
    pending_operations: list[PendingOperationResponse]
    drifts: list[PositionDriftResponse] = Field(default_factory=list)
    money_rub: float
    last_synced_at: str | None = None
    has_pending_top_up: bool = False
    pending_top_up_rub: float = 0.0
    top_up_auto_applied: bool = False
    top_up_distributed_rub: float = 0.0
    top_up_notes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConfirmPendingRequest(BaseModel):
    lots: int | None = Field(default=None, ge=1)
    price_pct: float | None = Field(default=None, gt=0)


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


class PutOfferDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(exercise|hold)$")


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
