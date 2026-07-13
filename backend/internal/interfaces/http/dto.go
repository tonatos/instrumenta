package httpapi

import (
	"encoding/json"
	"io"
)

// ConfigResponse mirrors ConfigResponse in api.py.
type ConfigResponse struct {
	KeyRate                 float64 `json:"key_rate"`
	TaxRate                 float64 `json:"tax_rate"`
	MaxDays                 int     `json:"max_days"`
	MinVolumeRub            float64 `json:"min_volume_rub"`
	TinkoffConfigured       bool    `json:"tinkoff_configured"`
	SandboxConfigured       bool    `json:"sandbox_configured"`
	ProductionConfigured    bool    `json:"production_configured"`
	AuthEnabled             bool    `json:"auth_enabled"`
	TelegramOIDCConfigured  bool    `json:"telegram_oidc_configured"`
}

type AuthMeResponse struct {
	TelegramID  int64  `json:"telegram_id"`
	DisplayName string `json:"display_name"`
}

type BondResponse struct {
	Secid                 string             `json:"secid"`
	ISIN                  string             `json:"isin"`
	Name                  string             `json:"name"`
	FIGI                  string             `json:"figi"`
	MaturityDate          *string            `json:"maturity_date"`
	OfferDate             *string            `json:"offer_date"`
	OfferSubmissionStart  *string            `json:"offer_submission_start"`
	OfferSubmissionEnd    *string            `json:"offer_submission_end"`
	OfferPricePct         *float64           `json:"offer_price_pct"`
	OfferKind             *string            `json:"offer_kind"`
	OfferWindowStatus     *string            `json:"offer_window_status"`
	CallDate              *string            `json:"call_date"`
	EffectiveDate         *string            `json:"effective_date"`
	DaysToMaturity        *int               `json:"days_to_maturity"`
	YTM                   *float64           `json:"ytm"`
	YTMNet                *float64           `json:"ytm_net"`
	CouponRate            *float64           `json:"coupon_rate"`
	CouponType            string             `json:"coupon_type"`
	LastPrice             *float64           `json:"last_price"`
	FaceValue             float64            `json:"face_value"`
	LotSize               int                `json:"lot_size"`
	DurationYears         *float64           `json:"duration_years"`
	VolumeRub             *float64           `json:"volume_rub"`
	PrevVolumeRub         *float64           `json:"prev_volume_rub"`
	CreditRating          *string            `json:"credit_rating"`
	RiskLevel             int                `json:"risk_level"`
	Score                 *float64           `json:"score"`
	ProfileScores         map[string]float64 `json:"profile_scores"`
	DurationAdjustment    *float64           `json:"duration_adjustment"`
	YTMScore              *float64           `json:"ytm_score"`
	RiskScore             *float64           `json:"risk_score"`
	LiquidityScore        *float64           `json:"liquidity_score"`
	IsFavorite            bool               `json:"is_favorite"`
	HasWarnings           bool               `json:"has_warnings"`
	Warnings              []string           `json:"warnings"`
	TinvestEnriched       bool               `json:"tinvest_enriched"`
	IssuerName            string             `json:"issuer_name"`
	InstrumentFullName    string             `json:"instrument_full_name"`
	Sector                string             `json:"sector"`
	Description           string             `json:"description"`
}

type BondsListResponse struct {
	Bonds    []BondResponse `json:"bonds"`
	Source   string         `json:"source"`
	Count    int            `json:"count"`
	Total    int            `json:"total"`
	Page     int            `json:"page"`
	PageSize int            `json:"page_size"`
}

type CreatePortfolioRequest struct {
	Name                     string   `json:"name"`
	InitialAmountRub         float64  `json:"initial_amount_rub"`
	HorizonDate              string   `json:"horizon_date"`
	RiskProfile              string   `json:"risk_profile"`
	APITradeOnly             *bool    `json:"api_trade_only"`
	MaxWeightedDurationYears *float64 `json:"max_weighted_duration_years"`
	TargetDurationYears      *float64 `json:"target_duration_years"`
}

type UpdatePortfolioRequest struct {
	Name                     *string  `json:"name"`
	InitialAmountRub         *float64 `json:"initial_amount_rub"`
	HorizonDate              *string  `json:"horizon_date"`
	RiskProfile              *string  `json:"risk_profile"`
	APITradeOnly             *bool    `json:"api_trade_only"`
	MaxWeightedDurationYears *float64 `json:"max_weighted_duration_years"`
	TargetDurationYears      *float64 `json:"target_duration_years"`
}

type PortfolioPositionData struct {
	ISIN                 string   `json:"isin"`
	Secid                string   `json:"secid"`
	Name                 string   `json:"name"`
	Lots                 int      `json:"lots"`
	LotSize              int      `json:"lot_size"`
	PurchaseCleanPricePct float64 `json:"purchase_clean_price_pct"`
	PurchaseDirtyPriceRub float64 `json:"purchase_dirty_price_rub"`
	PurchaseACIRub       float64  `json:"purchase_aci_rub"`
	PurchaseDate         string   `json:"purchase_date"`
	PurchaseAmountRub    float64  `json:"purchase_amount_rub"`
	CouponRate           *float64 `json:"coupon_rate"`
	FaceValue            float64  `json:"face_value"`
	MaturityDate         *string  `json:"maturity_date"`
	OfferDate            *string  `json:"offer_date"`
	OfferSubmissionStart *string  `json:"offer_submission_start"`
	OfferSubmissionEnd   *string  `json:"offer_submission_end"`
	OfferPricePct        *float64 `json:"offer_price_pct"`
	PutOfferDecision     string   `json:"put_offer_decision"`
	OfferKind            *string  `json:"offer_kind"`
	OfferWindowStatus    *string  `json:"offer_window_status"`
	CouponPeriodDays     *int     `json:"coupon_period_days"`
	NextCouponDate       *string  `json:"next_coupon_date"`
	Source               string   `json:"source"`
	FIGI                 *string  `json:"figi"`
	Status               *string  `json:"status"`
}

type ReinvestmentSlotData struct {
	TriggerDate        string   `json:"trigger_date"`
	TriggerReason      string   `json:"trigger_reason"`
	ExpectedCashRub    float64  `json:"expected_cash_rub"`
	SuggestedISIN      *string  `json:"suggested_isin"`
	SuggestedName      *string  `json:"suggested_name"`
	ConfirmedISIN      *string  `json:"confirmed_isin"`
	GapDays            int      `json:"gap_days"`
	SourcePositionISIN *string  `json:"source_position_isin"`
}

type FrozenForecastData struct {
	ExpectedXIRRPct           *float64 `json:"expected_xirr_pct"`
	ExpectedTotalNetProfitRub   float64  `json:"expected_total_net_profit_rub"`
	ExpectedFinalValueRub       float64  `json:"expected_final_value_rub"`
	FrozenInitialAmountRub      float64  `json:"frozen_initial_amount_rub"`
	HorizonDate                 string   `json:"horizon_date"`
	CreatedAt                   string   `json:"created_at"`
}

type PortfolioDataResponse struct {
	ID                       string                   `json:"id"`
	Name                     string                   `json:"name"`
	CreatedAt                string                   `json:"created_at"`
	UpdatedAt                string                   `json:"updated_at"`
	InitialAmountRub         float64                  `json:"initial_amount_rub"`
	HorizonDate              string                   `json:"horizon_date"`
	RiskProfile              string                   `json:"risk_profile"`
	APITradeOnly             bool                     `json:"api_trade_only"`
	MaxWeightedDurationYears *float64                 `json:"max_weighted_duration_years"`
	TargetDurationYears      *float64                 `json:"target_duration_years"`
	CashBalanceRub           float64                  `json:"cash_balance_rub"`
	Mode                     string                   `json:"mode"`
	AccountID                *string                  `json:"account_id"`
	AccountKind              *string                  `json:"account_kind"`
	AccountLabel             *string                  `json:"account_label"`
	TradingStartedAt         *string                  `json:"trading_started_at"`
	FrozenForecast           *FrozenForecastData      `json:"frozen_forecast"`
	Positions                []PortfolioPositionData  `json:"positions"`
	Slots                    []ReinvestmentSlotData   `json:"slots"`
	ClosedPositionsCount     int                      `json:"closed_positions_count"`
}

type PortfolioResponse struct {
	ID                   string                `json:"id"`
	Name                 string                `json:"name"`
	InitialAmountRub     float64               `json:"initial_amount_rub"`
	HorizonDate          string                `json:"horizon_date"`
	RiskProfile          string                `json:"risk_profile"`
	CashBalanceRub       float64               `json:"cash_balance_rub"`
	Mode                 string                `json:"mode"`
	AccountID            *string               `json:"account_id"`
	AccountKind          *string               `json:"account_kind"`
	PositionsCount       int                   `json:"positions_count"`
	ClosedPositionsCount int                   `json:"closed_positions_count"`
	InvestedCapitalRub   float64               `json:"invested_capital_rub"`
	Data                 PortfolioDataResponse `json:"data"`
}

type PlanResponse struct {
	TotalNetProfitRub          float64          `json:"total_net_profit_rub"`
	TotalNetProfitWithHeldRub  float64          `json:"total_net_profit_with_held_rub"`
	InvestedCapitalRub         float64          `json:"invested_capital_rub"`
	TotalInvestedRub           float64          `json:"total_invested_rub"`
	FinalCashBalance           float64          `json:"final_cash_balance"`
	FinalPortfolioValue        float64          `json:"final_portfolio_value"`
	InitialCashRub             float64          `json:"initial_cash_rub"`
	ExpectedXIRRPct            *float64         `json:"expected_xirr_pct"`
	WeightedDurationYears      *float64         `json:"weighted_duration_years"`
	Notes                      []string         `json:"notes"`
	Cashflow                   []map[string]any `json:"cashflow"`
	ValueTimeline              []map[string]any `json:"value_timeline"`
	HeldPositions              []map[string]any `json:"held_positions"`
	Slots                      []map[string]any `json:"slots"`
	UpcomingPutOffers          []map[string]any `json:"upcoming_put_offers"`
}

type AddPositionRequest struct {
	ISIN string `json:"isin"`
	Lots int    `json:"lots"`
}

type SetSlotOverrideRequest struct {
	SourcePositionISIN string  `json:"source_position_isin"`
	ConfirmedISIN      *string `json:"confirmed_isin"`
}

type SetPutOfferDecisionRequest struct {
	Decision string `json:"decision"`
}

type CalculatorRequest struct {
	Secids    []string `json:"secids"`
	BudgetRub float64  `json:"budget_rub"`
}

type CalculatorResponse struct {
	Results            []map[string]any `json:"results"`
	TotalInvestedRub   float64          `json:"total_invested_rub"`
	TotalProfitRub     float64          `json:"total_profit_rub"`
	PortfolioYieldPct  *float64         `json:"portfolio_yield_pct"`
}

type HoldingResponse struct {
	FIGI            string   `json:"figi"`
	ISIN            string   `json:"isin"`
	Name            string   `json:"name"`
	Lots            int      `json:"lots"`
	Quantity        int      `json:"quantity"`
	LotSize         int      `json:"lot_size"`
	CurrentPricePct *float64 `json:"current_price_pct"`
	CurrentNKDRub   *float64 `json:"current_nkd_rub"`
	YTM             *float64 `json:"ytm"`
	MaturityDate    *string  `json:"maturity_date"`
	OfferDate       *string  `json:"offer_date"`
	MarketValueRub  *float64 `json:"market_value_rub"`
}

type SuggestionResponse struct {
	ID                string   `json:"id"`
	Kind              string   `json:"kind"`
	ISIN              string   `json:"isin"`
	Name              string   `json:"name"`
	Lots              int      `json:"lots"`
	FIGI              *string  `json:"figi"`
	SuggestedPricePct *float64 `json:"suggested_price_pct"`
	MarketPricePct    *float64 `json:"market_price_pct"`
	Reason            string   `json:"reason"`
	DueDate           *string  `json:"due_date"`
	SourceISIN        *string  `json:"source_isin"`
	ChatTemplate      *string  `json:"chat_template"`
	Urgency           string   `json:"urgency"`
	RiskAcknowledgeable bool   `json:"risk_acknowledgeable"`
	OfferWindowStatus *string  `json:"offer_window_status"`
	SubmissionStart   *string  `json:"submission_start"`
	SubmissionEnd     *string  `json:"submission_end"`
}

type ActiveOrderResponse struct {
	OrderID              string   `json:"order_id"`
	RequestUID           string   `json:"request_uid"`
	FIGI                 string   `json:"figi"`
	Direction            string   `json:"direction"`
	LotsRequested        int      `json:"lots_requested"`
	LotsExecuted         int      `json:"lots_executed"`
	Status               string   `json:"status"`
	PricePct             *float64 `json:"price_pct"`
	TotalOrderAmountRub  *float64 `json:"total_order_amount_rub"`
	InitialCommissionRub *float64 `json:"initial_commission_rub"`
}

type PerformanceDataResponse struct {
	XIRRPct            *float64 `json:"xirr_pct"`
	CouponsReceivedRub float64  `json:"coupons_received_rub"`
	TaxPaidRub         float64  `json:"tax_paid_rub"`
	CommissionPaidRub  float64  `json:"commission_paid_rub"`
	RealizedProfitRub  float64  `json:"realized_profit_rub"`
	UnrealizedValueRub float64  `json:"unrealized_value_rub"`
	InvestedRub        float64  `json:"invested_rub"`
	ReceivedRub        float64  `json:"received_rub"`
	AsOf               string   `json:"as_of"`
}

type DeploySessionProgressResponse struct {
	Total   int `json:"total"`
	Pending int `json:"pending"`
	Placed  int `json:"placed"`
	Filled  int `json:"filled"`
	Skipped int `json:"skipped"`
	Stale   int `json:"stale"`
}

type DeploySessionItemResponse struct {
	ID                 string   `json:"id"`
	Kind               string   `json:"kind"`
	ISIN               string   `json:"isin"`
	Name               string   `json:"name"`
	Lots               int      `json:"lots"`
	FIGI               *string  `json:"figi"`
	SuggestedPricePct  float64  `json:"suggested_price_pct"`
	EstimatedAmountRub float64  `json:"estimated_amount_rub"`
	Reason             string   `json:"reason"`
	Status             string   `json:"status"`
	SourceISIN         *string  `json:"source_isin"`
	DueDate            *string  `json:"due_date"`
	OrderID            *string  `json:"order_id"`
	Urgency            string   `json:"urgency"`
}

type DeploySessionResponse struct {
	ID              string                      `json:"id"`
	Status          string                      `json:"status"`
	ExpiresAt       string                      `json:"expires_at"`
	CashSnapshotRub float64                     `json:"cash_snapshot_rub"`
	Progress        DeploySessionProgressResponse `json:"progress"`
	Items           []DeploySessionItemResponse `json:"items"`
	Warnings        []string                    `json:"warnings"`
}

type TradingAdviceResponse struct {
	Holdings              []HoldingResponse          `json:"holdings"`
	Cashflow              []map[string]any           `json:"cashflow"`
	Performance           *PerformanceDataResponse   `json:"performance"`
	Suggestions           []SuggestionResponse       `json:"suggestions"`
	ActiveOrders          []ActiveOrderResponse      `json:"active_orders"`
	MoneyRub              float64                    `json:"money_rub"`
	AvailableMoneyRub     float64                    `json:"available_money_rub"`
	BlockedMoneyRub       float64                    `json:"blocked_money_rub"`
	Warnings              []string                   `json:"warnings"`
	AsOf                  string                     `json:"as_of"`
	WeightedDurationYears *float64                   `json:"weighted_duration_years"`
	DeploySession         *DeploySessionResponse     `json:"deploy_session"`
}

type TradingStateResponse struct {
	Plan   PlanResponse          `json:"plan"`
	Advice TradingAdviceResponse `json:"advice"`
}

type PlaceOrderRequest struct {
	ISIN         string   `json:"isin"`
	Direction    string   `json:"direction"`
	Lots         int      `json:"lots"`
	PricePct     float64  `json:"price_pct"`
	FIGI         *string  `json:"figi"`
	SuggestionID *string  `json:"suggestion_id"`
}

type PlaceOrderResponse struct {
	OrderID              string   `json:"order_id"`
	Status               string   `json:"status"`
	RequestUID           string   `json:"request_uid"`
	LotsRequested        int      `json:"lots_requested"`
	LotsExecuted         int      `json:"lots_executed"`
	TotalOrderAmountRub  *float64 `json:"total_order_amount_rub"`
	InitialCommissionRub *float64 `json:"initial_commission_rub"`
}

type OrderPreviewResponse struct {
	OrderLots            int      `json:"order_lots"`
	OrderBonds           int      `json:"order_bonds"`
	LotSize              int      `json:"lot_size"`
	OrderPricePct        float64  `json:"order_price_pct"`
	CleanAmountRub       float64  `json:"clean_amount_rub"`
	ACIRubPerBond        float64  `json:"aci_rub_per_bond"`
	LocalTotalAmountRub  float64  `json:"local_total_amount_rub"`
	BrokerCleanAmountRub *float64 `json:"broker_clean_amount_rub"`
	BrokerACIAmountRub   *float64 `json:"broker_aci_amount_rub"`
	BrokerTotalAmountRub *float64 `json:"broker_total_amount_rub"`
	BrokerCommissionRub  *float64 `json:"broker_commission_rub"`
	MoneyRub             float64  `json:"money_rub"`
	SufficientCash       bool     `json:"sufficient_cash"`
	PreviewSource        string   `json:"preview_source"`
	MarketPricePct       *float64 `json:"market_price_pct"`
	FaceValueRub         float64  `json:"face_value_rub"`
}

type SellPositionRequest struct {
	Lots     int     `json:"lots"`
	PricePct float64 `json:"price_pct"`
}

type SellQuoteResponse struct {
	MarketPricePct     float64 `json:"market_price_pct"`
	SuggestedPricePct  float64 `json:"suggested_price_pct"`
	AvailableLots      int     `json:"available_lots"`
	SellBufferLabel    string  `json:"sell_buffer_label"`
}

type SellPositionPreviewResponse struct {
	OrderPreviewResponse
	AvailableLots     int      `json:"available_lots"`
	SufficientLots    bool     `json:"sufficient_lots"`
	SuggestedPricePct *float64 `json:"suggested_price_pct"`
}

type NotificationResponse struct {
	ID          string         `json:"id"`
	Fingerprint string         `json:"fingerprint"`
	PortfolioID string         `json:"portfolio_id"`
	Kind        string         `json:"kind"`
	Payload     map[string]any `json:"payload"`
	Urgency     string         `json:"urgency"`
	CreatedAt   string         `json:"created_at"`
	ReadAt      *string        `json:"read_at"`
	DismissedAt *string        `json:"dismissed_at"`
	IsUnread    bool           `json:"is_unread"`
}

type NotificationsListResponse struct {
	Notifications []NotificationResponse `json:"notifications"`
}

type HealthResponse struct {
	Status string `json:"status"`
}

// JSONMap is a loose JSON object for dynamic handler responses.
type JSONMap map[string]any

func decodeJSON(r io.Reader, dst any) error {
	dec := json.NewDecoder(r)
	dec.DisallowUnknownFields()
	return dec.Decode(dst)
}
