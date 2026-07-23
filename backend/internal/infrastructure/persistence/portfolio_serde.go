package persistence

import (
	"encoding/json"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
)

type portfolioDataJSON struct {
	APITradeOnly             bool                           `json:"api_trade_only"`
	TurboEntryEnabled        bool                           `json:"turbo_entry_enabled"`
	MaxWeightedDurationYears *float64                       `json:"max_weighted_duration_years"`
	TargetDurationYears      *float64                       `json:"target_duration_years"`
	AccountLabel             *string                        `json:"account_label"`
	TradingStartedAt         *string                        `json:"trading_started_at"`
	FrozenForecast           *frozenForecastJSON            `json:"frozen_forecast"`
	RiskBaselines            map[string]riskSnapshotJSON    `json:"risk_baselines"`
	Positions                []portfolioPositionJSON        `json:"positions"`
	Slots                    []reinvestmentSlotJSON         `json:"slots"`
}

type frozenForecastJSON struct {
	ExpectedXIRRPct           *float64 `json:"expected_xirr_pct"`
	ExpectedTotalNetProfitRub float64  `json:"expected_total_net_profit_rub"`
	ExpectedFinalValueRub     float64  `json:"expected_final_value_rub"`
	FrozenInitialAmountRub    float64  `json:"frozen_initial_amount_rub"`
	HorizonDate               string   `json:"horizon_date"`
	CreatedAt                 string   `json:"created_at"`
}

type riskSnapshotJSON struct {
	HasDefault          bool    `json:"has_default"`
	HasTechnicalDefault bool    `json:"has_technical_default"`
	CreditRating        *string `json:"credit_rating"`
}

type portfolioPositionJSON struct {
	ISIN                     string   `json:"isin"`
	Secid                    string   `json:"secid"`
	Name                     string   `json:"name"`
	Lots                     int      `json:"lots"`
	LotSize                  int      `json:"lot_size"`
	PurchaseCleanPricePct    float64  `json:"purchase_clean_price_pct"`
	PurchaseDirtyPriceRub    float64  `json:"purchase_dirty_price_rub"`
	PurchaseACIRub           float64  `json:"purchase_aci_rub"`
	PurchaseDate             string   `json:"purchase_date"`
	PurchaseAmountRub        float64  `json:"purchase_amount_rub"`
	CouponRate               *float64 `json:"coupon_rate"`
	FaceValue                float64  `json:"face_value"`
	MaturityDate             *string  `json:"maturity_date"`
	OfferDate                *string  `json:"offer_date"`
	OfferSubmissionStart     *string  `json:"offer_submission_start"`
	OfferSubmissionEnd       *string  `json:"offer_submission_end"`
	OfferPricePct            *float64 `json:"offer_price_pct"`
	CouponPeriodDays         *int     `json:"coupon_period_days"`
	NextCouponDate           *string  `json:"next_coupon_date"`
	Source                   string   `json:"source"`
	FIGI                     *string  `json:"figi"`
	PutOfferDecision         string   `json:"put_offer_decision"`
}

type reinvestmentSlotJSON struct {
	TriggerDate        string           `json:"trigger_date"`
	TriggerReason      string           `json:"trigger_reason"`
	ExpectedCashRub    float64          `json:"expected_cash_rub"`
	SuggestedISIN      *string          `json:"suggested_isin"`
	SuggestedName      *string          `json:"suggested_name"`
	ConfirmedISIN      *string          `json:"confirmed_isin"`
	GapDays            int              `json:"gap_days"`
	SourcePositionISIN *string          `json:"source_position_isin"`
	Status             string           `json:"status"`
	FailureReason      *string          `json:"failure_reason"`
	EligibleCandidates []map[string]any `json:"eligible_candidates"`
}

func portfolioToDataJSON(p portfolio.Portfolio) ([]byte, error) {
	data := portfolioDataJSON{
		APITradeOnly:             p.APITradeOnly,
		TurboEntryEnabled:        p.TurboEntryEnabled,
		MaxWeightedDurationYears: p.MaxWeightedDurationYears,
		TargetDurationYears:      p.TargetDurationYears,
		AccountLabel:             p.AccountLabel,
		TradingStartedAt:         p.TradingStartedAt,
		RiskBaselines:            make(map[string]riskSnapshotJSON, len(p.RiskBaselines)),
		Positions:                make([]portfolioPositionJSON, 0, len(p.Positions)),
		Slots:                    make([]reinvestmentSlotJSON, 0, len(p.Slots)),
	}
	if p.FrozenForecast != nil {
		ff := p.FrozenForecast
		data.FrozenForecast = &frozenForecastJSON{
			ExpectedXIRRPct:           ff.ExpectedXIRRPct,
			ExpectedTotalNetProfitRub: ff.ExpectedTotalNetProfitRub,
			ExpectedFinalValueRub:     ff.ExpectedFinalValueRub,
			FrozenInitialAmountRub:    ff.FrozenInitialAmountRub,
			HorizonDate:               ff.HorizonDate.Format("2006-01-02"),
			CreatedAt:                 ff.CreatedAt,
		}
	}
	for isin, snap := range p.RiskBaselines {
		data.RiskBaselines[isin] = riskSnapshotJSON{
			HasDefault: snap.HasDefault, HasTechnicalDefault: snap.HasTechnicalDefault,
			CreditRating: snap.CreditRating,
		}
	}
	for _, pos := range p.Positions {
		data.Positions = append(data.Positions, positionToJSON(pos))
	}
	for _, slot := range p.Slots {
		data.Slots = append(data.Slots, slotToJSON(slot))
	}
	return json.Marshal(data)
}

func portfolioFromRow(row portfolioRow) (portfolio.Portfolio, error) {
	var data portfolioDataJSON
	if row.Data != "" {
		if err := json.Unmarshal([]byte(row.Data), &data); err != nil {
			return portfolio.Portfolio{}, err
		}
	}
	p := portfolio.Portfolio{
		ID: row.ID, Name: row.Name,
		CreatedAt: row.CreatedAt,
		UpdatedAt: row.UpdatedAt,
		OwnerTelegramID: row.OwnerTelegramID,
		InitialAmountRub: row.InitialAmountRub,
		HorizonDate:      parseDate(row.HorizonDate),
		RiskProfile:      portfolio.RiskProfile(row.RiskProfile),
		CashBalanceRub:   row.CashBalanceRub,
		Mode:             portfolio.PortfolioMode(row.Mode),
		APITradeOnly:     data.APITradeOnly,
		TurboEntryEnabled: data.TurboEntryEnabled,
		MaxWeightedDurationYears: data.MaxWeightedDurationYears,
		TargetDurationYears:      data.TargetDurationYears,
		AccountLabel:             data.AccountLabel,
		TradingStartedAt:         data.TradingStartedAt,
		RiskBaselines:            make(map[string]portfolio.RiskSnapshot),
	}
	if row.AccountID.Valid {
		p.AccountID = &row.AccountID.String
	}
	if row.AccountKind.Valid {
		k := portfolio.AccountKind(row.AccountKind.String)
		p.AccountKind = &k
	}
	if data.FrozenForecast != nil {
		ff := data.FrozenForecast
		hd, _ := time.Parse("2006-01-02", ff.HorizonDate)
		p.FrozenForecast = &portfolio.FrozenForecast{
			ExpectedXIRRPct: ff.ExpectedXIRRPct,
			ExpectedTotalNetProfitRub: ff.ExpectedTotalNetProfitRub,
			ExpectedFinalValueRub:     ff.ExpectedFinalValueRub,
			FrozenInitialAmountRub:    ff.FrozenInitialAmountRub,
			HorizonDate:               hd,
			CreatedAt:                 ff.CreatedAt,
		}
	}
	for isin, snap := range data.RiskBaselines {
		p.RiskBaselines[isin] = portfolio.RiskSnapshot{
			HasDefault: snap.HasDefault, HasTechnicalDefault: snap.HasTechnicalDefault,
			CreditRating: snap.CreditRating,
		}
	}
	for _, pos := range data.Positions {
		p.Positions = append(p.Positions, positionFromJSON(pos))
	}
	for _, slot := range data.Slots {
		p.Slots = append(p.Slots, slotFromJSON(slot))
	}
	return p, nil
}

func positionToJSON(p portfolio.PortfolioPosition) portfolioPositionJSON {
	return portfolioPositionJSON{
		ISIN: p.ISIN, Secid: p.Secid, Name: p.Name, Lots: p.Lots, LotSize: p.LotSize,
		PurchaseCleanPricePct: p.PurchaseCleanPricePct, PurchaseDirtyPriceRub: p.PurchaseDirtyPriceRub,
		PurchaseACIRub: p.PurchaseACIRub, PurchaseDate: p.PurchaseDate.Format("2006-01-02"),
		PurchaseAmountRub: p.PurchaseAmountRub, CouponRate: p.CouponRate, FaceValue: p.FaceValue,
		MaturityDate: datePtrToStr(p.MaturityDate), OfferDate: datePtrToStr(p.OfferDate),
		OfferSubmissionStart: datePtrToStr(p.OfferSubmissionStart),
		OfferSubmissionEnd:   datePtrToStr(p.OfferSubmissionEnd),
		OfferPricePct: p.OfferPricePct, CouponPeriodDays: p.CouponPeriodDays,
		NextCouponDate: datePtrToStr(p.NextCouponDate),
		Source: string(p.Source), FIGI: p.FIGI,
		PutOfferDecision: string(p.PutOfferDecision),
	}
}

func positionFromJSON(j portfolioPositionJSON) portfolio.PortfolioPosition {
	return portfolio.PortfolioPosition{
		ISIN: j.ISIN, Secid: j.Secid, Name: j.Name, Lots: j.Lots, LotSize: j.LotSize,
		PurchaseCleanPricePct: j.PurchaseCleanPricePct, PurchaseDirtyPriceRub: j.PurchaseDirtyPriceRub,
		PurchaseACIRub: j.PurchaseACIRub, PurchaseDate: parseDate(j.PurchaseDate),
		PurchaseAmountRub: j.PurchaseAmountRub, CouponRate: j.CouponRate, FaceValue: j.FaceValue,
		MaturityDate: strToDatePtr(j.MaturityDate), OfferDate: strToDatePtr(j.OfferDate),
		OfferSubmissionStart: strToDatePtr(j.OfferSubmissionStart),
		OfferSubmissionEnd:   strToDatePtr(j.OfferSubmissionEnd),
		OfferPricePct: j.OfferPricePct, CouponPeriodDays: j.CouponPeriodDays,
		NextCouponDate: strToDatePtr(j.NextCouponDate),
		Source: portfolio.PositionSourceType(j.Source), FIGI: j.FIGI,
		PutOfferDecision: bonds.PutOfferDecision(j.PutOfferDecision),
	}
}

func slotToJSON(s portfolio.ReinvestmentSlot) reinvestmentSlotJSON {
	return reinvestmentSlotJSON{
		TriggerDate: s.TriggerDate.Format("2006-01-02"), TriggerReason: string(s.TriggerReason),
		ExpectedCashRub: s.ExpectedCashRub, SuggestedISIN: s.SuggestedISIN, SuggestedName: s.SuggestedName,
		ConfirmedISIN: s.ConfirmedISIN, GapDays: s.GapDays, SourcePositionISIN: s.SourcePositionISIN,
		Status: string(s.Status), FailureReason: s.FailureReason, EligibleCandidates: s.EligibleCandidates,
	}
}

func slotFromJSON(j reinvestmentSlotJSON) portfolio.ReinvestmentSlot {
	return portfolio.ReinvestmentSlot{
		TriggerDate: parseDate(j.TriggerDate), TriggerReason: portfolio.ReinvestmentTriggerReason(j.TriggerReason),
		ExpectedCashRub: j.ExpectedCashRub, SuggestedISIN: j.SuggestedISIN, SuggestedName: j.SuggestedName,
		ConfirmedISIN: j.ConfirmedISIN, GapDays: j.GapDays, SourcePositionISIN: j.SourcePositionISIN,
		Status: portfolio.ReinvestmentSlotStatus(j.Status), FailureReason: j.FailureReason,
		EligibleCandidates: j.EligibleCandidates,
	}
}

func parseDate(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		t, _ = time.Parse(time.RFC3339, s)
	}
	return t
}

func datePtrToStr(t *time.Time) *string {
	if t == nil {
		return nil
	}
	s := t.Format("2006-01-02")
	return &s
}

func strToDatePtr(s *string) *time.Time {
	if s == nil || *s == "" {
		return nil
	}
	t := parseDate(*s)
	return &t
}
