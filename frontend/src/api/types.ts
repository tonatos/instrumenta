export interface Bond {
  secid: string;
  isin: string;
  name: string;
  figi: string;
  maturity_date: string | null;
  offer_date: string | null;
  call_date: string | null;
  effective_date: string | null;
  days_to_maturity: number | null;
  ytm: number | null;
  ytm_net: number | null;
  coupon_rate: number | null;
  coupon_type: string;
  last_price: number | null;
  face_value: number;
  lot_size: number;
  duration_years: number | null;
  volume_rub: number | null;
  prev_volume_rub: number | null;
  credit_rating: string | null;
  risk_level: number;
  score: number | null;
  ytm_score: number | null;
  risk_score: number | null;
  liquidity_score: number | null;
  is_favorite: boolean;
  has_warnings: boolean;
  warnings: string[];
  tinvest_enriched: boolean;
  issuer_name: string;
  instrument_full_name: string;
  sector: string;
  description: string;
}

export interface BondsListResponse {
  bonds: Bond[];
  source: string;
  count: number;
}

export interface ConfigResponse {
  key_rate: number;
  tax_rate: number;
  max_days: number;
  min_volume_rub: number;
  tinkoff_configured: boolean;
  sandbox_configured: boolean;
  production_configured: boolean;
  auth_enabled: boolean;
  telegram_oidc_configured: boolean;
}

export interface TelegramOidcStartResponse {
  authorization_url: string;
}

export interface TelegramOidcCallbackRequest {
  code: string;
  state: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
}

export interface AuthMeResponse {
  telegram_id: number;
  display_name: string;
}

export type PositionStatus = "pending" | "active" | "drift" | "closed";

export interface PortfolioPosition {
  isin: string;
  secid: string;
  name: string;
  lots: number;
  lot_size: number;
  purchase_clean_price_pct: number;
  purchase_dirty_price_rub: number;
  purchase_aci_rub: number;
  purchase_date: string;
  purchase_amount_rub: number;
  coupon_rate: number | null;
  face_value: number;
  maturity_date: string | null;
  offer_date: string | null;
  source: string;
  figi: string | null;
  status?: PositionStatus;
}

export interface ReinvestmentSlotCandidate {
  isin: string;
  name: string;
  score: number | null;
  ytm_net: number | null;
}

export type ReinvestmentSlotStatus =
  | "ok"
  | "no_candidate"
  | "invalid_selection"
  | "insufficient_cash";

export type ReinvestmentSelectionMode = "strategy" | "manual";

export interface ReinvestmentSlot {
  trigger_date: string;
  trigger_reason: string;
  expected_cash_rub: number;
  suggested_isin: string | null;
  suggested_name: string | null;
  confirmed_isin: string | null;
  gap_days: number;
  source_position_isin: string | null;
  selection_mode: ReinvestmentSelectionMode;
  status: ReinvestmentSlotStatus;
  failure_reason: string | null;
  eligible_candidates: ReinvestmentSlotCandidate[];
}

export interface PortfolioData {
  positions: PortfolioPosition[];
  slots: ReinvestmentSlot[];
  cash_balance_rub: number;
  initial_amount_rub: number;
  horizon_date: string;
  mode: string;
  api_trade_only?: boolean;
  max_weighted_duration_years?: number | null;
  target_duration_years?: number | null;
  account_id: string | null;
  account_kind: string | null;
  frozen_forecast: {
    expected_xirr_pct: number | null;
    expected_total_net_profit_rub: number;
    expected_final_value_rub: number;
    frozen_initial_amount_rub: number;
    horizon_date: string;
    created_at: string;
  } | null;
}

export interface Portfolio {
  id: string;
  name: string;
  initial_amount_rub: number;
  horizon_date: string;
  risk_profile: string;
  cash_balance_rub: number;
  mode: string;
  account_id: string | null;
  account_kind: string | null;
  positions_count: number;
  closed_positions_count?: number;
  invested_capital_rub: number;
  api_trade_only?: boolean;
  max_weighted_duration_years?: number | null;
  data: PortfolioData;
}

export interface PlanResponse {
  total_net_profit_rub: number;
  total_net_profit_with_held_rub: number;
  invested_capital_rub: number;
  total_invested_rub: number;
  final_cash_balance: number;
  final_portfolio_value: number;
  expected_xirr_pct: number | null;
  weighted_duration_years: number | null;
  notes: string[];
  cashflow: Array<{
    date: string;
    amount_rub: number;
    kind: string;
    label: string;
    lots?: number | null;
    bonds_count?: number | null;
  }>;
  value_timeline: Array<{
    date: string;
    cash_rub: number;
    positions_value_rub: number;
    total_value_rub: number;
  }>;
  held_positions: Array<{
    isin: string;
    name: string;
    lots: number;
    estimated_value_rub: number;
    maturity_date: string | null;
  }>;
  slots: ReinvestmentSlot[];
}

export interface CalculatorResponse {
  results: Array<{
    secid: string;
    name: string;
    lots: number;
    invested_rub: number;
    coupon_income_rub: number;
    profit_rub: number;
    hold_days: number;
  }>;
  total_invested_rub: number;
  total_profit_rub: number;
  portfolio_yield_pct: number | null;
}

export interface LinkedPortfolioPreview {
  id: string;
  name: string;
}

export interface BrokerAccount {
  id: string;
  name: string;
  kind: string;
  money_rub?: number;
  linked_portfolio?: LinkedPortfolioPreview | null;
}

export interface DeleteSandboxAccountResult {
  account_id: string;
  deleted_portfolio_id: string | null;
}

export interface AccountBondPositionPreview {
  figi: string;
  ticker: string;
  quantity: number;
  lots: number;
  current_price_pct: number | null;
}

export interface AccountOtherInstrumentPreview {
  instrument_type: string;
  ticker: string;
  figi: string;
  quantity: number;
}

export interface AccountPreview {
  money_rub: number;
  bond_positions: AccountBondPositionPreview[];
  other_instruments: AccountOtherInstrumentPreview[];
  has_securities: boolean;
  can_attach: boolean;
  blockers: string[];
  warnings: string[];
  sold_count?: number;
  sold?: Array<{
    figi: string;
    ticker: string;
    lots: number;
    order_id: string;
    status: string;
  }>;
  account_id?: string;
  account_replaced?: { old_id: string; new_id: string };
  reset_note?: string;
  linked_portfolio?: LinkedPortfolioPreview | null;
}

export interface TradingAdviceResponse {
  holdings: HoldingView[];
  cashflow: CashflowEventView[];
  performance: PerformanceData | null;
  suggestions: Suggestion[];
  active_orders: ActiveOrder[];
  money_rub: number;
  available_money_rub: number;
  blocked_money_rub: number;
  warnings: string[];
  as_of: string;
  weighted_duration_years: number | null;
}

export interface TradingStateResponse {
  plan: PlanResponse;
  advice: TradingAdviceResponse;
}

export interface HoldingView {
  figi: string;
  isin: string;
  name: string;
  lots: number;
  quantity: number;
  lot_size: number;
  current_price_pct: number | null;
  current_nkd_rub: number | null;
  ytm: number | null;
  maturity_date: string | null;
  offer_date: string | null;
  market_value_rub: number | null;
}

export interface CashflowEventView {
  date: string;
  kind: string;
  amount_rub: number;
  description: string;
  related_isin?: string | null;
  is_projected?: boolean;
}

export interface PerformanceData {
  xirr_pct: number | null;
  coupons_received_rub: number;
  tax_paid_rub: number;
  commission_paid_rub: number;
  realized_profit_rub: number;
  unrealized_value_rub: number;
  invested_rub: number;
  received_rub: number;
  as_of: string;
}

export type SuggestionKind = "buy" | "reinvest" | "put_offer_reminder" | "sell";

export type SuggestionUrgency = "normal" | "soon" | "critical";

export interface Suggestion {
  id: string;
  kind: SuggestionKind;
  isin: string;
  name: string;
  lots: number;
  figi: string | null;
  suggested_price_pct: number | null;
  market_price_pct?: number | null;
  reason: string;
  due_date: string | null;
  source_isin?: string | null;
  chat_template?: string | null;
  urgency: SuggestionUrgency;
}

export interface ActiveOrder {
  order_id: string;
  request_uid: string;
  figi: string;
  direction: "BUY" | "SELL";
  lots_requested: number;
  lots_executed: number;
  status: string;
  price_pct: number | null;
  total_order_amount_rub: number | null;
  initial_commission_rub: number | null;
}

export interface PlaceOrderRequest {
  isin: string;
  direction: "BUY" | "SELL";
  lots: number;
  price_pct: number;
  figi?: string | null;
  suggestion_id?: string | null;
}

export interface PlaceOrderResponse {
  order_id: string;
  status: string;
  request_uid: string;
  lots_requested: number;
  lots_executed: number;
  total_order_amount_rub: number | null;
  initial_commission_rub: number | null;
}

export interface SandboxPayInResponse {
  amount_added_rub: number;
  money_rub: number;
}

export interface AccountOperation {
  id: string;
  type: string;
  type_label: string;
  state: string;
  state_label: string;
  date: string;
  figi: string;
  instrument_type: string;
  isin: string | null;
  name: string | null;
  payment_rub: number | null;
  quantity: number;
  price_pct: number | null;
  commission_rub: number | null;
}

export interface AccountOperationsResponse {
  operations: AccountOperation[];
}

export interface OrderPreviewResponse {
  order_lots: number;
  order_bonds: number;
  lot_size: number;
  order_price_pct: number;
  clean_amount_rub: number;
  aci_rub_per_bond: number;
  local_total_amount_rub: number;
  broker_clean_amount_rub: number | null;
  broker_aci_amount_rub: number | null;
  broker_total_amount_rub: number | null;
  broker_commission_rub: number | null;
  money_rub: number;
  sufficient_cash: boolean;
  preview_source: "broker" | "moex";
  market_price_pct?: number | null;
  face_value_rub?: number;
}

export interface SellPositionPreviewResponse extends OrderPreviewResponse {
  available_lots: number;
  sufficient_lots: boolean;
  suggested_price_pct: number | null;
}

export interface SellQuoteResponse {
  market_price_pct: number;
  suggested_price_pct: number;
  available_lots: number;
  sell_buffer_label: string;
}
