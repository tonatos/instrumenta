export type OfferWindowStatus =
  | "unknown"
  | "not_open"
  | "open"
  | "closed"
  | "expired";

export interface Bond {
  secid: string;
  isin: string;
  name: string;
  figi: string;
  maturity_date: string | null;
  offer_date: string | null;
  offer_submission_start?: string | null;
  offer_submission_end?: string | null;
  offer_price_pct?: number | null;
  offer_kind?: string | null;
  offer_window_status?: OfferWindowStatus | null;
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
  profile_scores?: Record<string, number>;
  duration_adjustment?: number | null;
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
  total: number;
  page: number;
  page_size: number;
}

export interface BondListParams {
  filter_by?: "effective" | "maturity";
  max_days?: number;
  min_volume_rub?: number;
  min_ytm_net?: number;
  max_lot_price_rub?: number;
  coupon_types?: string[];
  risk_levels?: number[];
  sectors?: string[];
  hide_default?: boolean;
  hide_subordinated?: boolean;
  q?: string;
  sort_by?: string;
  sort_desc?: boolean;
  page?: number;
  page_size?: number;
  export?: boolean;
  risk_profile?: string;
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
  credentials: {
    sandbox?: { fingerprint: string; updated_at: string };
    production?: { fingerprint: string; updated_at: string };
  };
}

export interface BrokerCredentialStatus {
  fingerprint: string;
  updated_at: string;
}

export type PositionStatus = "pending" | "active" | "drift" | "closed";

export type PutOfferDecision = "pending" | "exercise" | "hold";

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
  offer_submission_start?: string | null;
  offer_submission_end?: string | null;
  offer_price_pct?: number | null;
  put_offer_decision?: PutOfferDecision;
  offer_kind?: string | null;
  offer_window_status?: OfferWindowStatus | null;
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
  turbo_entry_enabled?: boolean;
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
  initial_cash_rub: number;
  expected_xirr_pct: number | null;
  weighted_duration_years: number | null;
  notes: string[];
  cashflow_from_date?: string | null;
  cashflow: Array<{
    date: string;
    amount_rub: number;
    kind: string;
    label: string;
    lots?: number | null;
    bonds_count?: number | null;
    balance_after_rub?: number;
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
  upcoming_put_offers?: UpcomingPutOffer[];
}

export interface UpcomingPutOffer {
  isin: string;
  name: string;
  offer_date: string | null;
  submission_start: string | null;
  submission_end: string | null;
  offer_price_pct: number | null;
  days_until: number;
  days_until_submission_end: number | null;
  can_exercise: boolean;
  put_offer_decision: PutOfferDecision;
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
  deploy_session?: DeploySessionResponse | null;
}

export type DeploySessionItemStatus =
  | "pending"
  | "placed"
  | "filled"
  | "skipped"
  | "stale";

export interface DeploySessionProgress {
  total: number;
  pending: number;
  placed: number;
  filled: number;
  skipped: number;
  stale: number;
}

export interface DeploySessionItem {
  id: string;
  kind: "buy" | "reinvest";
  isin: string;
  name: string;
  lots: number;
  figi: string | null;
  suggested_price_pct: number;
  estimated_amount_rub: number;
  reason: string;
  status: DeploySessionItemStatus;
  source_isin?: string | null;
  due_date?: string | null;
  order_id?: string | null;
  urgency?: string;
}

export interface DeploySessionResponse {
  id: string;
  status: string;
  expires_at: string;
  cash_snapshot_rub: number;
  progress: DeploySessionProgress;
  items: DeploySessionItem[];
  warnings: string[];
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

export type SuggestionKind =
  | "buy"
  | "reinvest"
  | "reinvest_watch"
  | "put_offer_reminder"
  | "put_offer_watch"
  | "sell";

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
  risk_acknowledgeable?: boolean;
  offer_window_status?: OfferWindowStatus | null;
  submission_start?: string | null;
  submission_end?: string | null;
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

export type NotificationKind =
  | "put_offer_action"
  | "risk_escalation"
  | "put_offer_watch"
  | "sector_concentration"
  | "spread_anomaly"
  | "spread_widening"
  | "sector_stress"
  | "turbo_entry";

export interface Notification {
  id: string;
  fingerprint: string;
  portfolio_id: string;
  kind: NotificationKind;
  payload: Record<string, unknown>;
  urgency: SuggestionUrgency;
  created_at: string;
  read_at: string | null;
  dismissed_at: string | null;
  is_unread: boolean;
}

export interface NotificationsListResponse {
  notifications: Notification[];
}

export interface MarketRadarSectorRow {
  sector: string;
  change_7d_pct: number;
  anomaly_count: number;
  dip_idea_count: number;
  bond_count: number;
  in_portfolios?: string[];
}

export interface MarketRadarAnomalyRow {
  isin: string;
  secid: string;
  name: string;
  sector: string;
  spread_pp: number;
  expected_spread_pp: number;
  delta_pp: number;
  z_score?: number | null;
  peers: number;
  in_portfolios?: string[];
}

export interface MarketRadarDipIdeaRow {
  isin: string;
  secid: string;
  name: string;
  sector: string;
  bond_change_7d_pct: number;
  sector_change_7d_pct: number;
  idiosyncratic_excess_pct: number;
  score: number;
  interpretation: string;
  in_portfolios?: string[];
}

export interface MarketRadarResponse {
  scanned_at: string;
  universe_scanned: number;
  sectors: MarketRadarSectorRow[];
  anomalies: MarketRadarAnomalyRow[];
  dip_ideas: MarketRadarDipIdeaRow[];
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
