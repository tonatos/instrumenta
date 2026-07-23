package httpapi

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/screening"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
)

func emptySlice[T any](items []T) []T {
	if items == nil {
		return []T{}
	}
	return items
}

func ptrDate(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := shared.FormatISODate(*t)
	return &s
}

func offerScheduleFromBond(b bonds.BondRecord) bonds.OfferSchedule {
	return bondOfferAdapter{b}
}

type bondOfferAdapter struct{ b bonds.BondRecord }

func (a bondOfferAdapter) GetOfferDate() *time.Time             { return a.b.OfferDate }
func (a bondOfferAdapter) GetOfferSubmissionStart() *time.Time  { return a.b.OfferSubmissionStart }
func (a bondOfferAdapter) GetOfferSubmissionEnd() *time.Time  { return a.b.OfferSubmissionEnd }
func (a bondOfferAdapter) GetOfferPricePct() *float64         { return a.b.OfferPricePct }
func (a bondOfferAdapter) GetCallDate() *time.Time            { return a.b.CallDate }

func screeningPolicyFromPortfolio(p portfolio.DurationPolicy) screening.DurationPolicy {
	return screening.DurationPolicy{
		MaxWeightedDurationYears: p.MaxWeightedDurationYears,
		TargetDurationYears:      p.TargetDurationYears,
		DurationScoreWeight:      p.DurationScoreWeight,
		RateScenario:             screening.RateScenario(p.RateScenario),
		FloaterRateDurationYears: p.FloaterRateDurationYears,
	}
}

func BondToResponse(
	bond bonds.BondRecord,
	activeProfile portfolio.RiskProfile,
	durationPolicy portfolio.DurationPolicy,
	durationScale *float64,
) BondResponse {
	screeningPolicy := screeningPolicyFromPortfolio(durationPolicy)
	scale := 0.0
	if durationScale != nil {
		scale = *durationScale
	} else {
		scale = screening.DurationScaleYears([]bonds.BondRecord{bond}, screeningPolicy)
	}
	resolved := screening.ResolveProfileScores(&bond, screeningPolicy, scale)
	activeScore := resolved[string(activeProfile)]
	if activeScore == 0 && bond.Score != nil {
		activeScore = *bond.Score
	}
	durationAdj := screening.DurationAdjustmentForBond(&bond, screeningPolicy, scale)
	var durationAdjPtr *float64
	if durationAdj != 0 {
		durationAdjPtr = &durationAdj
	}
	view := bonds.BondOfferViewFrom(offerScheduleFromBond(bond), time.Now())
	var offerKind, offerWindow *string
	if view != nil {
		k := string(view.Kind)
		w := string(view.WindowStatus)
		offerKind = &k
		offerWindow = &w
	}
	warnings := emptySlice(bond.WarningsList())
	return BondResponse{
		Secid:                bond.Secid,
		ISIN:                 bond.ISIN,
		Name:                 bond.Name,
		FIGI:                 bond.FIGI,
		MaturityDate:         ptrDate(bond.MaturityDate),
		OfferDate:            ptrDate(bond.OfferDate),
		OfferSubmissionStart: ptrDate(bond.OfferSubmissionStart),
		OfferSubmissionEnd:   ptrDate(bond.OfferSubmissionEnd),
		OfferPricePct:        bond.OfferPricePct,
		OfferKind:            offerKind,
		OfferWindowStatus:    offerWindow,
		CallDate:             ptrDate(bond.CallDate),
		EffectiveDate:        ptrDate(bond.EffectiveDate),
		DaysToMaturity:       bond.DaysToMaturity,
		YTM:                  bond.YTM,
		YTMNet:               bond.YTMNet,
		CouponRate:           bond.CouponRate,
		CouponType:           string(bond.CouponType),
		LastPrice:            bond.LastPrice,
		FaceValue:            bond.FaceValue,
		LotSize:              bond.LotSize,
		DurationYears:        bond.DurationYears(),
		VolumeRub:            bond.VolumeRub,
		PrevVolumeRub:        bond.PrevVolumeRub,
		CreditRating:         bond.CreditRating,
		RiskLevel:            int(bond.RiskLevel),
		Score:                &activeScore,
		ProfileScores:        resolved,
		DurationAdjustment:   durationAdjPtr,
		YTMScore:             bond.YTMScore,
		RiskScore:            bond.RiskScore,
		LiquidityScore:       bond.LiquidityScore,
		IsFavorite:           bond.IsFavorite,
		HasWarnings:          bond.HasWarnings(),
		Warnings:             warnings,
		TinvestEnriched:      bond.TInvestEnriched,
		IssuerName:           bond.IssuerName,
		InstrumentFullName:   bond.InstrumentFullName,
		Sector:               bond.Sector,
		Description:          bond.Description,
	}
}

func positionToAPIData(position portfolio.PortfolioPosition, isTrading bool, today time.Time) PortfolioPositionData {
	_ = isTrading
	_ = today
	status := "active"
	view := bonds.BondOfferViewFrom(&position, today)
	var offerKind, offerWindow *string
	if view != nil {
		k := string(view.Kind)
		w := string(view.WindowStatus)
		offerKind = &k
		offerWindow = &w
	}
	return PortfolioPositionData{
		ISIN:                  position.ISIN,
		Secid:                 position.Secid,
		Name:                  position.Name,
		Lots:                  position.Lots,
		LotSize:               position.LotSize,
		PurchaseCleanPricePct: position.PurchaseCleanPricePct,
		PurchaseDirtyPriceRub: position.PurchaseDirtyPriceRub,
		PurchaseACIRub:        position.PurchaseACIRub,
		PurchaseDate:          shared.FormatISODate(position.PurchaseDate),
		PurchaseAmountRub:     position.PurchaseAmountRub,
		CouponRate:            position.CouponRate,
		FaceValue:             position.FaceValue,
		MaturityDate:          ptrDate(position.MaturityDate),
		OfferDate:             ptrDate(position.OfferDate),
		OfferSubmissionStart:  ptrDate(position.OfferSubmissionStart),
		OfferSubmissionEnd:    ptrDate(position.OfferSubmissionEnd),
		OfferPricePct:         position.OfferPricePct,
		PutOfferDecision:      string(position.PutOfferDecision),
		OfferKind:             offerKind,
		OfferWindowStatus:     offerWindow,
		CouponPeriodDays:      position.CouponPeriodDays,
		NextCouponDate:        ptrDate(position.NextCouponDate),
		Source:                string(position.Source),
		FIGI:                  position.FIGI,
		Status:                &status,
	}
}

func slotToData(slot portfolio.ReinvestmentSlot) ReinvestmentSlotData {
	return ReinvestmentSlotData{
		TriggerDate:        shared.FormatISODate(slot.TriggerDate),
		TriggerReason:      string(slot.TriggerReason),
		ExpectedCashRub:    slot.ExpectedCashRub,
		SuggestedISIN:      slot.SuggestedISIN,
		SuggestedName:      slot.SuggestedName,
		ConfirmedISIN:      slot.ConfirmedISIN,
		GapDays:            slot.GapDays,
		SourcePositionISIN: slot.SourcePositionISIN,
	}
}

func slotToPlanDict(slot portfolio.ReinvestmentSlot) map[string]any {
	data := map[string]any{
		"trigger_date":         shared.FormatISODate(slot.TriggerDate),
		"trigger_reason":       string(slot.TriggerReason),
		"expected_cash_rub":    slot.ExpectedCashRub,
		"suggested_isin":       slot.SuggestedISIN,
		"suggested_name":       slot.SuggestedName,
		"confirmed_isin":       slot.ConfirmedISIN,
		"gap_days":             slot.GapDays,
		"source_position_isin": slot.SourcePositionISIN,
		"selection_mode":       slot.SelectionMode(),
		"status":               string(slot.Status),
		"failure_reason":       slot.FailureReason,
		"eligible_candidates":  slot.EligibleCandidates,
	}
	return data
}

func PortfolioToResponse(p portfolio.Portfolio, today time.Time) PortfolioResponse {
	if today.IsZero() {
		today = time.Now()
	}
	open := portfolio.OpenPositions(p.Positions)
	closed := len(p.Positions) - len(open)
	positions := make([]PortfolioPositionData, 0, len(p.Positions))
	for _, pos := range p.Positions {
		positions = append(positions, positionToAPIData(pos, p.IsTrading(), today))
	}
	slots := make([]ReinvestmentSlotData, 0, len(p.Slots))
	for _, slot := range p.Slots {
		slots = append(slots, slotToData(slot))
	}
	var accountKind *string
	if p.AccountKind != nil {
		s := string(*p.AccountKind)
		accountKind = &s
	}
	var frozen *FrozenForecastData
	if p.FrozenForecast != nil {
		ff := p.FrozenForecast
		frozen = &FrozenForecastData{
			ExpectedXIRRPct:           ff.ExpectedXIRRPct,
			ExpectedTotalNetProfitRub: ff.ExpectedTotalNetProfitRub,
			ExpectedFinalValueRub:     ff.ExpectedFinalValueRub,
			FrozenInitialAmountRub:    ff.FrozenInitialAmountRub,
			HorizonDate:               shared.FormatISODate(ff.HorizonDate),
			CreatedAt:                 ff.CreatedAt,
		}
	}
	data := PortfolioDataResponse{
		ID:                       p.ID,
		Name:                     p.Name,
		CreatedAt:                p.CreatedAt,
		UpdatedAt:                p.UpdatedAt,
		InitialAmountRub:         p.InitialAmountRub,
		HorizonDate:              shared.FormatISODate(p.HorizonDate),
		RiskProfile:              string(p.RiskProfile),
		APITradeOnly:             p.APITradeOnly,
		TurboEntryEnabled:        p.TurboEntryEnabled,
		MaxWeightedDurationYears: p.MaxWeightedDurationYears,
		TargetDurationYears:      p.TargetDurationYears,
		CashBalanceRub:           p.CashBalanceRub,
		Mode:                     string(p.Mode),
		AccountID:                p.AccountID,
		AccountKind:              accountKind,
		AccountLabel:             p.AccountLabel,
		TradingStartedAt:         p.TradingStartedAt,
		FrozenForecast:           frozen,
		Positions:                positions,
		Slots:                    slots,
		ClosedPositionsCount:     closed,
	}
	return PortfolioResponse{
		ID:                   p.ID,
		Name:                 p.Name,
		InitialAmountRub:     p.InitialAmountRub,
		HorizonDate:          shared.FormatISODate(p.HorizonDate),
		RiskProfile:          string(p.RiskProfile),
		CashBalanceRub:       p.CashBalanceRub,
		Mode:                 string(p.Mode),
		AccountID:            p.AccountID,
		AccountKind:          accountKind,
		PositionsCount:       len(open),
		ClosedPositionsCount: closed,
		InvestedCapitalRub:   portfolio.InvestedCapitalRub(p, nil),
		Data:                 data,
	}
}

func PlanToResponse(plan portfolio.PortfolioPlan) PlanResponse {
	cashflow := make([]map[string]any, 0)
	for _, row := range portfolio.CashflowProjectedRowsFromToday(plan.Events, plan.InitialCashRub, plan.AsOf) {
		cashflow = append(cashflow, map[string]any{
			"date":              row.Date,
			"amount_rub":        row.AmountRub,
			"kind":              row.Kind,
			"label":             row.Label,
			"lots":              row.Lots,
			"bonds_count":       row.BondsCount,
			"balance_after_rub": row.BalanceAfterRub,
		})
	}
	valueTimeline := make([]map[string]any, 0, len(plan.ValueTimeline))
	for _, p := range plan.ValueTimeline {
		valueTimeline = append(valueTimeline, map[string]any{
			"date":                shared.FormatISODate(p.Date),
			"cash_rub":            p.CashRub,
			"positions_value_rub": p.PositionsValueRub,
			"total_value_rub":     p.TotalValueRub,
		})
	}
	held := make([]map[string]any, 0, len(plan.HeldPositions))
	for _, h := range plan.HeldPositions {
		var maturity *string
		if h.Position.MaturityDate != nil {
			s := shared.FormatISODate(*h.Position.MaturityDate)
			maturity = &s
		}
		held = append(held, map[string]any{
			"isin":                h.Position.ISIN,
			"name":                h.Position.Name,
			"lots":                h.Position.Lots,
			"estimated_value_rub": h.EstimatedValueRub,
			"maturity_date":       maturity,
		})
	}
	slots := make([]map[string]any, 0, len(plan.ResolvedSlots))
	for _, s := range plan.ResolvedSlots {
		slots = append(slots, slotToPlanDict(s))
	}
	putOffers := make([]map[string]any, 0, len(plan.UpcomingPutOffers))
	for _, item := range plan.UpcomingPutOffers {
		var offerDate, subStart, subEnd *string
		if item.Position.OfferDate != nil {
			s := shared.FormatISODate(*item.Position.OfferDate)
			offerDate = &s
		}
		if item.SubmissionStart != nil {
			s := shared.FormatISODate(*item.SubmissionStart)
			subStart = &s
		}
		if item.SubmissionEnd != nil {
			s := shared.FormatISODate(*item.SubmissionEnd)
			subEnd = &s
		}
		putOffers = append(putOffers, map[string]any{
			"isin":                       item.Position.ISIN,
			"name":                       item.Position.Name,
			"offer_date":                 offerDate,
			"submission_start":           subStart,
			"submission_end":             subEnd,
			"offer_price_pct":            item.OfferPricePct,
			"days_until":                 item.DaysUntil,
			"days_until_submission_end":  item.DaysUntilSubmissionEnd,
			"can_exercise":               item.CanExercise,
			"put_offer_decision":         string(item.Position.PutOfferDecision),
		})
	}
	var cashflowFrom *string
	if !plan.AsOf.IsZero() {
		s := shared.FormatISODate(plan.AsOf)
		cashflowFrom = &s
	}
	return PlanResponse{
		TotalNetProfitRub:         plan.TotalNetProfitRub,
		TotalNetProfitWithHeldRub: plan.TotalNetProfitWithHeldRub,
		InvestedCapitalRub:        plan.InvestedCapitalRub,
		TotalInvestedRub:          plan.TotalInvestedRub,
		FinalCashBalance:          plan.FinalCashBalanceRub,
		FinalPortfolioValue:       plan.FinalPortfolioValueRub,
		InitialCashRub:            plan.InitialCashRub,
		ExpectedXIRRPct:           plan.EffectiveAnnualReturnPct,
		WeightedDurationYears:     plan.WeightedDurationYears,
		Notes:                     emptySlice(plan.Notes),
		Cashflow:                  emptySlice(cashflow),
		CashflowFromDate:          cashflowFrom,
		ValueTimeline:             valueTimeline,
		HeldPositions:             held,
		Slots:                     slots,
		UpcomingPutOffers:         putOffers,
	}
}

func ConfigToResponse(settings config.Settings, keyRatePP, taxRatePct float64) ConfigResponse {
	return ConfigResponse{
		KeyRate:                keyRatePP,
		TaxRate:                taxRatePct,
		MaxDays:                settings.MaxDays,
		MinVolumeRub:           settings.MinVolumeRub,
		TinkoffConfigured:      settings.TinkoffToken != "",
		// Deprecated: trading flags are per-user via GET /auth/me credentials.
		SandboxConfigured:      false,
		ProductionConfigured:   false,
		AuthEnabled:            settings.AuthEnabled(),
		TelegramOIDCConfigured: settings.TelegramOIDCConfigured(),
	}
}

func AdviceToResponse(result application.TradingAdviceResult) TradingAdviceResponse {
	var performance *PerformanceDataResponse
	if result.Performance != nil {
		p := result.Performance
		performance = &PerformanceDataResponse{
			XIRRPct:            p.XIRRPct,
			CouponsReceivedRub: float64(p.CouponsReceivedRub),
			TaxPaidRub:         float64(p.TaxPaidRub),
			CommissionPaidRub:  float64(p.CommissionPaidRub),
			RealizedProfitRub:  float64(p.RealizedProfitRub),
			UnrealizedValueRub: float64(p.UnrealizedValueRub),
			InvestedRub:        float64(p.InvestedRub),
			ReceivedRub:        float64(p.ReceivedRub),
			AsOf:               p.AsOf,
		}
	}
	holdings := make([]HoldingResponse, 0, len(result.Holdings))
	for _, h := range result.Holdings {
		holdings = append(holdings, HoldingToResponse(h))
	}
	suggestions := make([]SuggestionResponse, 0, len(result.Suggestions))
	for _, s := range result.Suggestions {
		suggestions = append(suggestions, SuggestionToResponse(s))
	}
	orders := make([]ActiveOrderResponse, 0, len(result.ActiveOrders))
	for _, o := range result.ActiveOrders {
		orders = append(orders, ActiveOrderToResponse(o))
	}
	return TradingAdviceResponse{
		Holdings:              holdings,
		Cashflow:              emptySlice(result.Cashflow),
		Performance:           performance,
		Suggestions:           suggestions,
		ActiveOrders:          orders,
		MoneyRub:              result.MoneyRub,
		AvailableMoneyRub:     result.AvailableMoneyRub,
		BlockedMoneyRub:       result.BlockedMoneyRub,
		Warnings:              emptySlice(result.Warnings),
		AsOf:                  result.AsOf,
		WeightedDurationYears: result.WeightedDurationYears,
		DeploySession:         DeploySessionToResponse(result.DeploySession),
	}
}

func HoldingToResponse(h trading.HoldingView) HoldingResponse {
	return HoldingResponse{
		FIGI:            h.FIGI,
		ISIN:            h.ISIN,
		Name:            h.Name,
		Lots:            h.Lots,
		Quantity:        h.Quantity,
		LotSize:         h.LotSize,
		CurrentPricePct: h.CurrentPricePct,
		CurrentNKDRub:   h.CurrentNKDRub,
		YTM:             h.YTM,
		MaturityDate:    ptrDate(h.MaturityDate),
		OfferDate:       ptrDate(h.OfferDate),
		MarketValueRub:  h.MarketValueRub,
	}
}

func SuggestionToResponse(s trading.Suggestion) SuggestionResponse {
	return SuggestionResponse{
		ID:                s.ID,
		Kind:              string(s.Kind),
		ISIN:              s.ISIN,
		Name:              s.Name,
		Lots:              s.Lots,
		FIGI:              s.FIGI,
		SuggestedPricePct: s.SuggestedPricePct,
		MarketPricePct:    s.MarketPricePct,
		Reason:            s.Reason,
		DueDate:           ptrDate(s.DueDate),
		SourceISIN:        s.SourceISIN,
		ChatTemplate:      s.ChatTemplate,
		Urgency:           string(s.Urgency),
		RiskAcknowledgeable: s.RiskAcknowledgeable,
		OfferWindowStatus: s.OfferWindowStatus,
		SubmissionStart:   ptrDate(s.SubmissionStart),
		SubmissionEnd:     ptrDate(s.SubmissionEnd),
	}
}

func ActiveOrderToResponse(o trading.BrokerActiveOrder) ActiveOrderResponse {
	return ActiveOrderResponse{
		OrderID:              o.OrderID,
		RequestUID:           o.RequestUID,
		FIGI:                 o.FIGI,
		Direction:            o.Direction,
		LotsRequested:        o.LotsRequested,
		LotsExecuted:         o.LotsExecuted,
		Status:               o.Status,
		PricePct:             o.PricePct,
		TotalOrderAmountRub:  o.TotalOrderAmountRub,
		InitialCommissionRub: o.InitialCommissionRub,
	}
}

func DeploySessionToResponse(session *trading.DeploySession) *DeploySessionResponse {
	if session == nil {
		return nil
	}
	progress := trading.DeploySessionProgressOf(*session)
	items := make([]DeploySessionItemResponse, 0, len(session.Items))
	for _, item := range session.Items {
		items = append(items, DeploySessionItemToResponse(item))
	}
	return &DeploySessionResponse{
		ID:              session.ID,
		Status:          string(session.Status),
		ExpiresAt:       session.ExpiresAt.UTC().Format(time.RFC3339),
		CashSnapshotRub: session.CashSnapshotRub,
		Progress: DeploySessionProgressResponse{
			Total:   progress.Total,
			Pending: progress.Pending,
			Placed:  progress.Placed,
			Filled:  progress.Filled,
			Skipped: progress.Skipped,
			Stale:   progress.Stale,
		},
		Items:    items,
		Warnings: emptySlice(session.Warnings),
	}
}

func DeploySessionItemToResponse(item trading.DeploySessionItem) DeploySessionItemResponse {
	return DeploySessionItemResponse{
		ID:                 item.ID,
		Kind:               string(item.Kind),
		ISIN:               item.ISIN,
		Name:               item.Name,
		Lots:               item.Lots,
		FIGI:               item.FIGI,
		SuggestedPricePct:  item.SuggestedPricePct,
		EstimatedAmountRub: item.EstimatedAmountRub,
		Reason:             item.Reason,
		Status:             string(item.Status),
		SourceISIN:         item.SourceISIN,
		DueDate:            ptrDate(item.DueDate),
		OrderID:            item.OrderID,
		Urgency:            string(item.Urgency),
	}
}

func NotificationToResponse(record application.NotificationRecord) NotificationResponse {
	var readAt, dismissedAt *string
	if record.ReadAt != nil {
		s := record.ReadAt.UTC().Format(time.RFC3339)
		readAt = &s
	}
	if record.DismissedAt != nil {
		s := record.DismissedAt.UTC().Format(time.RFC3339)
		dismissedAt = &s
	}
	return NotificationResponse{
		ID:          record.ID,
		Fingerprint: record.Fingerprint,
		PortfolioID: record.PortfolioID,
		Kind:        record.Kind,
		Payload:     record.Payload,
		Urgency:     record.Urgency,
		CreatedAt:   record.CreatedAt.UTC().Format(time.RFC3339),
		ReadAt:      readAt,
		DismissedAt: dismissedAt,
		IsUnread:    record.IsUnread,
	}
}

func AccountOperationToResponse(op trading.BrokerOperation, bondsByFIGI map[string]bonds.BondRecord) AccountOperationResponse {
	bond, hasBond := bondsByFIGI[op.FIGI]
	var isin, name *string
	if hasBond {
		isin = &bond.ISIN
		name = &bond.Name
	}
	pricePct := op.PricePct
	if op.InstrumentType == "bond" && hasBond && bond.FaceValue > 0 && pricePct != nil {
		v := float64(shared.BondCleanPricePctFromRub(float64(*pricePct), bond.FaceValue))
		pricePctConverted := shared.PriceUnitPct(v)
		pricePct = &pricePctConverted
	}
	var priceOut *float64
	if pricePct != nil {
		v := float64(*pricePct)
		priceOut = &v
	}
	var payment, commission *float64
	if op.PaymentRub != nil {
		v := float64(*op.PaymentRub)
		payment = &v
	}
	if op.CommissionRub != nil {
		v := float64(*op.CommissionRub)
		commission = &v
	}
	return AccountOperationResponse{
		ID:              op.ID,
		Type:            op.Type,
		TypeLabel:       trading.OperationTypeLabel(op.Type),
		State:           op.State,
		StateLabel:      trading.OperationStateLabel(op.State),
		Date:            shared.FormatISODate(op.Date),
		FIGI:            op.FIGI,
		InstrumentType:  op.InstrumentType,
		ISIN:            isin,
		Name:            name,
		PaymentRub:      payment,
		Quantity:        op.Quantity,
		PricePct:        priceOut,
		CommissionRub:   commission,
	}
}

type AccountOperationResponse struct {
	ID             string   `json:"id"`
	Type           string   `json:"type"`
	TypeLabel      string   `json:"type_label"`
	State          string   `json:"state"`
	StateLabel     string   `json:"state_label"`
	Date           string   `json:"date"`
	FIGI           string   `json:"figi"`
	InstrumentType string   `json:"instrument_type"`
	ISIN           *string  `json:"isin"`
	Name           *string  `json:"name"`
	PaymentRub     *float64 `json:"payment_rub"`
	Quantity       int      `json:"quantity"`
	PricePct       *float64 `json:"price_pct"`
	CommissionRub  *float64 `json:"commission_rub"`
}

type AccountOperationsResponse struct {
	Operations []AccountOperationResponse `json:"operations"`
}
