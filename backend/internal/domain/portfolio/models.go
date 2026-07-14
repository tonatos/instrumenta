package portfolio

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

type RiskProfile string

const (
	RiskProfileConservative RiskProfile = "conservative"
	RiskProfileNormal       RiskProfile = "normal"
	RiskProfileAggressive   RiskProfile = "aggressive"
)

type PortfolioMode string

const (
	PortfolioModeSimulation PortfolioMode = "simulation"
	PortfolioModeTrading    PortfolioMode = "trading"
)

type PositionSourceType string

const (
	PositionSourceInitial          PositionSourceType = "initial"
	PositionSourceAdopted          PositionSourceType = "adopted"
	PositionSourceReinvestMaturity PositionSourceType = "reinvest_maturity"
	PositionSourceReinvestPutOffer PositionSourceType = "reinvest_put_offer"
	PositionSourceReinvestCoupon   PositionSourceType = "reinvest_coupon_cash"
)

type ReinvestmentTriggerReason string

const (
	TriggerMaturity   ReinvestmentTriggerReason = "maturity"
	TriggerPutOffer   ReinvestmentTriggerReason = "put_offer"
	TriggerCouponCash ReinvestmentTriggerReason = "coupon_cash"
)

type ReinvestmentSlotStatus string

const (
	SlotStatusOK               ReinvestmentSlotStatus = "ok"
	SlotStatusNoCandidate      ReinvestmentSlotStatus = "no_candidate"
	SlotStatusInvalidSelection ReinvestmentSlotStatus = "invalid_selection"
	SlotStatusInsufficientCash ReinvestmentSlotStatus = "insufficient_cash"
)

type AccountKind string

const (
	AccountKindSandbox    AccountKind = "sandbox"
	AccountKindProduction AccountKind = "production"
)

// PortfolioPosition is one held or planned bond lot.
type PortfolioPosition struct {
	ID int64 // simulation identity; not persisted

	ISIN                     string
	Secid                    string
	Name                     string
	Lots                     int
	LotSize                  int
	PurchaseCleanPricePct    float64
	PurchaseDirtyPriceRub    float64
	PurchaseACIRub           float64
	PurchaseDate             time.Time
	PurchaseAmountRub        float64
	CouponRate               *float64
	FaceValue                float64
	MaturityDate             *time.Time
	OfferDate                *time.Time
	OfferSubmissionStart     *time.Time
	OfferSubmissionEnd       *time.Time
	OfferPricePct            *float64
	CouponPeriodDays         *int
	NextCouponDate           *time.Time
	Source                   PositionSourceType
	FIGI                     *string
	PutOfferDecision         bonds.PutOfferDecision
}

func (p PortfolioPosition) BondsCount() int {
	return p.Lots * p.LotSize
}

func (p PortfolioPosition) GetOfferDate() *time.Time             { return p.OfferDate }
func (p PortfolioPosition) GetOfferSubmissionStart() *time.Time  { return p.OfferSubmissionStart }
func (p PortfolioPosition) GetOfferSubmissionEnd() *time.Time  { return p.OfferSubmissionEnd }
func (p PortfolioPosition) GetOfferPricePct() *float64         { return p.OfferPricePct }
func (p PortfolioPosition) GetCallDate() *time.Time            { return nil }

// ReinvestmentSlot describes a future reinvestment event in the plan timeline.
type ReinvestmentSlot struct {
	TriggerDate         time.Time
	TriggerReason       ReinvestmentTriggerReason
	ExpectedCashRub     float64
	SuggestedISIN       *string
	SuggestedName       *string
	ConfirmedISIN       *string
	GapDays             int
	SourcePositionISIN  *string
	Status              ReinvestmentSlotStatus
	FailureReason       *string
	EligibleCandidates  []map[string]any
}

func (s ReinvestmentSlot) SelectionMode() string {
	if s.ConfirmedISIN != nil {
		return "manual"
	}
	return "strategy"
}

func (s ReinvestmentSlot) EffectiveISIN() *string {
	if s.ConfirmedISIN != nil {
		return s.ConfirmedISIN
	}
	return s.SuggestedISIN
}

func (s ReinvestmentSlot) PurchaseDate() time.Time {
	return shared.AddDays(s.TriggerDate, s.GapDays)
}

// FrozenForecast is a scalar yield snapshot at trading-mode transition.
type FrozenForecast struct {
	ExpectedXIRRPct              *float64
	ExpectedTotalNetProfitRub    float64
	ExpectedFinalValueRub        float64
	FrozenInitialAmountRub       float64
	HorizonDate                  time.Time
	CreatedAt                    string
}

// Portfolio is persisted portfolio state.
type Portfolio struct {
	ID                       string
	Name                     string
	CreatedAt                string
	UpdatedAt                string
	InitialAmountRub         float64
	HorizonDate              time.Time
	RiskProfile              RiskProfile
	APITradeOnly             bool
	TurboEntryEnabled        bool
	MaxWeightedDurationYears *float64
	TargetDurationYears      *float64
	Positions                []PortfolioPosition
	Slots                    []ReinvestmentSlot
	CashBalanceRub           float64
	Mode                     PortfolioMode
	AccountID                *string
	AccountKind              *AccountKind
	AccountLabel             *string
	TradingStartedAt         *string
	FrozenForecast             *FrozenForecast
	RiskBaselines            map[string]RiskSnapshot
}

func (p Portfolio) IsTrading() bool {
	return p.Mode == PortfolioModeTrading
}

func (p *Portfolio) Touch() {
	p.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
}
