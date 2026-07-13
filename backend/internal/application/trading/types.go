package trading

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

// TradingAdviceResult is the API-facing trading advice DTO.
type TradingAdviceResult struct {
	Holdings              []HoldingResponse
	Cashflow              []map[string]any
	Performance           *PerformanceResponse
	Suggestions           []SuggestionResponse
	ActiveOrders          []ActiveOrderResponse
	MoneyRub              float64
	AvailableMoneyRub     float64
	BlockedMoneyRub       float64
	Warnings              []string
	AsOf                  string
	WeightedDurationYears *float64
	DeploySession         *DeploySessionResponse
}

type HoldingResponse struct {
	FIGI             string   `json:"figi"`
	ISIN             string   `json:"isin"`
	Name             string   `json:"name"`
	Lots             int      `json:"lots"`
	Quantity         int      `json:"quantity"`
	LotSize          int      `json:"lot_size"`
	CurrentPricePct  *float64 `json:"current_price_pct"`
	CurrentNKDRub    *float64 `json:"current_nkd_rub"`
	YTM              *float64 `json:"ytm"`
	MaturityDate     *string  `json:"maturity_date"`
	OfferDate        *string  `json:"offer_date"`
	MarketValueRub   *float64 `json:"market_value_rub"`
}

type SuggestionResponse struct {
	ID                   string   `json:"id"`
	Kind                 string   `json:"kind"`
	ISIN                 string   `json:"isin"`
	Name                 string   `json:"name"`
	Lots                 int      `json:"lots"`
	FIGI                 *string  `json:"figi"`
	SuggestedPricePct    float64  `json:"suggested_price_pct"`
	MarketPricePct       *float64 `json:"market_price_pct"`
	Reason               string   `json:"reason"`
	DueDate              *string  `json:"due_date"`
	SourceISIN           *string  `json:"source_isin"`
	ChatTemplate         *string  `json:"chat_template"`
	Urgency              string   `json:"urgency"`
	RiskAcknowledgeable  bool     `json:"risk_acknowledgeable"`
	OfferWindowStatus    *string  `json:"offer_window_status"`
	SubmissionStart      *string  `json:"submission_start"`
	SubmissionEnd        *string  `json:"submission_end"`
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

type PerformanceResponse struct {
	XIRRPct             *float64 `json:"xirr_pct"`
	CouponsReceivedRub  float64  `json:"coupons_received_rub"`
	TaxPaidRub          float64  `json:"tax_paid_rub"`
	CommissionPaidRub   float64  `json:"commission_paid_rub"`
	RealizedProfitRub   float64  `json:"realized_profit_rub"`
	UnrealizedValueRub  float64  `json:"unrealized_value_rub"`
	InvestedRub         float64  `json:"invested_rub"`
	ReceivedRub         float64  `json:"received_rub"`
	AsOf                string   `json:"as_of"`
}

type DeploySessionResponse struct {
	ID              string                       `json:"id"`
	Status          string                       `json:"status"`
	ExpiresAt       string                       `json:"expires_at"`
	CashSnapshotRub float64                      `json:"cash_snapshot_rub"`
	Progress        DeploySessionProgressResponse `json:"progress"`
	Items           []DeploySessionItemResponse  `json:"items"`
	Warnings        []string                     `json:"warnings"`
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

func holdingsToResponse(holdings []trading.HoldingView) []HoldingResponse {
	result := make([]HoldingResponse, 0, len(holdings))
	for _, h := range holdings {
		result = append(result, HoldingResponse{
			FIGI: h.FIGI, ISIN: h.ISIN, Name: h.Name, Lots: h.Lots, Quantity: h.Quantity, LotSize: h.LotSize,
			CurrentPricePct: h.CurrentPricePct, CurrentNKDRub: h.CurrentNKDRub, YTM: h.YTM,
			MaturityDate: datePtrToStr(h.MaturityDate), OfferDate: datePtrToStr(h.OfferDate),
			MarketValueRub: h.MarketValueRub,
		})
	}
	return result
}

func suggestionsToResponse(suggestions []trading.Suggestion) []SuggestionResponse {
	result := make([]SuggestionResponse, 0, len(suggestions))
	for _, s := range suggestions {
		result = append(result, SuggestionResponse{
			ID: s.ID, Kind: string(s.Kind), ISIN: s.ISIN, Name: s.Name, Lots: s.Lots, FIGI: s.FIGI,
			SuggestedPricePct: derefFloat(s.SuggestedPricePct), MarketPricePct: s.MarketPricePct, Reason: s.Reason,
			DueDate: datePtrToStr(s.DueDate), SourceISIN: s.SourceISIN, ChatTemplate: s.ChatTemplate,
			Urgency: string(s.Urgency), RiskAcknowledgeable: s.RiskAcknowledgeable,
			OfferWindowStatus: s.OfferWindowStatus,
			SubmissionStart: datePtrToStr(s.SubmissionStart), SubmissionEnd: datePtrToStr(s.SubmissionEnd),
		})
	}
	return result
}

func activeOrdersToResponse(orders []trading.BrokerActiveOrder) []ActiveOrderResponse {
	result := make([]ActiveOrderResponse, 0, len(orders))
	for _, o := range orders {
		result = append(result, ActiveOrderResponse{
			OrderID: o.OrderID, RequestUID: o.RequestUID, FIGI: o.FIGI, Direction: o.Direction,
			LotsRequested: o.LotsRequested, LotsExecuted: o.LotsExecuted, Status: o.Status,
			PricePct: o.PricePct, TotalOrderAmountRub: o.TotalOrderAmountRub, InitialCommissionRub: o.InitialCommissionRub,
		})
	}
	return result
}

func cashflowToResponse(events []portfolio.CashflowEvent) []map[string]any {
	result := make([]map[string]any, 0, len(events))
	for _, e := range events {
		result = append(result, map[string]any{
			"date": e.Date.Format("2006-01-02"), "kind": e.Kind, "amount_rub": e.AmountRub,
			"description": e.Description, "related_isin": e.RelatedISIN, "is_projected": e.IsProjected,
			"lots": e.Lots, "bonds_count": e.BondsCount,
		})
	}
	return result
}

func DeploySessionToResponse(session trading.DeploySession) DeploySessionResponse {
	progress := trading.DeploySessionProgressOf(session)
	items := make([]DeploySessionItemResponse, 0, len(session.Items))
	for _, item := range session.Items {
		items = append(items, DeploySessionItemResponse{
			ID: item.ID, Kind: string(item.Kind), ISIN: item.ISIN, Name: item.Name, Lots: item.Lots,
			FIGI: item.FIGI, SuggestedPricePct: item.SuggestedPricePct, EstimatedAmountRub: item.EstimatedAmountRub,
			Reason: item.Reason, Status: string(item.Status), SourceISIN: item.SourceISIN,
			DueDate: datePtrToStr(item.DueDate), OrderID: item.OrderID, Urgency: string(item.Urgency),
		})
	}
	return DeploySessionResponse{
		ID: session.ID, Status: string(session.Status), ExpiresAt: session.ExpiresAt.Format(time.RFC3339),
		CashSnapshotRub: session.CashSnapshotRub,
		Progress: DeploySessionProgressResponse{
			Total: progress.Total, Pending: progress.Pending, Placed: progress.Placed,
			Filled: progress.Filled, Skipped: progress.Skipped, Stale: progress.Stale,
		},
		Items: items, Warnings: session.Warnings,
	}
}

func derefFloat(v *float64) float64 {
	if v == nil {
		return 0
	}
	return *v
}

func datePtrToStr(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := t.Format("2006-01-02")
	return &s
}
