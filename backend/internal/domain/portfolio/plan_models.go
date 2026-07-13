package portfolio

import "time"

const (
	ReinvestmentGapDays       = 2
	MaxReinvestDepth          = 10
	MaxPositionShare          = 0.30
	TargetPositionShare       = 0.18
	MaxAutoPositions          = 10
	MinAutoPositions          = 4
	MinPositionAmountRub      = 5_000
	MinPositionShare          = 0.03
	MinReplacementHorizonDays = 10
	MinReinvestCleanPricePct  = 85
	SlotCandidatesLimit       = 30
)

// UpcomingPutOffer is a near-term put-offer requiring a decision.
type UpcomingPutOffer struct {
	Position                PortfolioPosition
	DaysUntil               int
	DaysUntilSubmissionEnd  *int
	SubmissionStart         *time.Time
	SubmissionEnd           *time.Time
	OfferPricePct           *float64
	CanExercise             bool
}

// HeldPositionAtHorizon describes a position still open at horizon.
type HeldPositionAtHorizon struct {
	Position          PortfolioPosition
	EstimatedValueRub float64
	ValuationSource   string
}

// PortfolioValuePoint is portfolio value at a date within the plan horizon.
type PortfolioValuePoint struct {
	Date               time.Time
	CashRub            float64
	PositionsValueRub  float64
	TotalValueRub      float64
}

// PortfolioPlan is a computed cashflow plan snapshot.
type PortfolioPlan struct {
	Portfolio                    Portfolio
	Events                       []CashflowEvent
	ResolvedSlots                []ReinvestmentSlot
	UpcomingPutOffers            []UpcomingPutOffer
	HeldPositions                []HeldPositionAtHorizon
	AllPositions                 []PortfolioPosition
	Notes                        []string
	TotalInvestedRub             float64
	TotalCouponGrossRub          float64
	TotalCouponNetRub            float64
	TotalTaxRub                  float64
	TotalRedemptionRub           float64
	FinalCashBalanceRub          float64
	HeldPositionsValueRub        float64
	FinalPortfolioValueRub       float64
	TotalNetProfitRub            float64
	TotalNetProfitWithHeldRub    float64
	InvestedCapitalRub           float64
	WeightedYTMNetPct            *float64
	WeightedYTMNetFullPct        *float64
	EffectiveAnnualReturnPct     *float64
	WeightedDurationYears        *float64
	HorizonDays                  int
	InitialCashRub               float64
	ValueTimeline                []PortfolioValuePoint
}
