package portfolio

import "time"

type PlanningPolicy struct {
	ReinvestmentGapDays   int
	PutOfferReminderDays  int
	MaxReinvestDepth      int
}

var DefaultPlanningPolicy = PlanningPolicy{
	ReinvestmentGapDays:  2,
	PutOfferReminderDays: 30,
	MaxReinvestDepth:     10,
}

type PortfolioAllocationPolicy struct {
	MaxPositionShare     float64
	TargetPositionShare  float64
	MaxAutoPositions     int
	MinAutoPositions     int
	MinPositionAmountRub float64
	MinPositionShare     float64
}

var DefaultPortfolioAllocationPolicy = PortfolioAllocationPolicy{
	MaxPositionShare:     0.30,
	TargetPositionShare: 0.18,
	MaxAutoPositions:     10,
	MinAutoPositions:     4,
	MinPositionAmountRub: 5_000,
	MinPositionShare:     0.03,
}

// DiversificationPolicy constrains portfolio concentration by issuer/sector.
// It is applied in compose/deploy pipelines as a guardrail, not as a score penalty.
type DiversificationPolicy struct {
	MaxSectorShare float64
	MaxIssuerShare float64
}

var DefaultDiversificationPolicy = DiversificationPolicy{
	MaxSectorShare: 0.35,
	MaxIssuerShare: 0.25,
}

type BondSelectionPolicy struct {
	MinCleanPricePct           float64
	MinReplacementHorizonDays  int
	ExcludeDefault             bool
}

var DefaultBondSelectionPolicy = BondSelectionPolicy{
	MinCleanPricePct:          85,
	MinReplacementHorizonDays: 10,
	ExcludeDefault:            true,
}

type RateScenario string

const (
	RateScenarioHold RateScenario = "hold"
	RateScenarioCut  RateScenario = "cut"
	RateScenarioHike RateScenario = "hike"
)

type DurationPolicy struct {
	MaxWeightedDurationYears *float64
	TargetDurationYears      *float64
	DurationScoreWeight      float64
	RateScenario             RateScenario
	FloaterRateDurationYears float64
}

var DefaultDurationPolicy = DurationPolicy{
	FloaterRateDurationYears: 0,
	RateScenario:             RateScenarioHold,
}

var scenarioDurationWeight = map[RateScenario]float64{
	RateScenarioHold: 0,
	RateScenarioCut:  0.20,
	RateScenarioHike: 0.20,
}

var scenarioDefaultTargetYears = map[RateScenario]*float64{
	RateScenarioHold: nil,
	RateScenarioCut:  floatPtr(2.0),
	RateScenarioHike: floatPtr(0.5),
}

func floatPtr(v float64) *float64 { return &v }

func ResolveDurationPolicy(
	rateScenario RateScenario,
	maxWeightedDurationYears, targetDurationYears *float64,
) DurationPolicy {
	weight := scenarioDurationWeight[rateScenario]
	target := targetDurationYears
	if target == nil {
		target = scenarioDefaultTargetYears[rateScenario]
	}
	if rateScenario == RateScenarioHold {
		target = nil
	}
	return DurationPolicy{
		MaxWeightedDurationYears: maxWeightedDurationYears,
		TargetDurationYears:      target,
		DurationScoreWeight:      weight,
		RateScenario:             rateScenario,
		FloaterRateDurationYears: 0,
	}
}

func DurationPolicyForPortfolio(p Portfolio, rateScenario RateScenario) DurationPolicy {
	return ResolveDurationPolicy(rateScenario, p.MaxWeightedDurationYears, p.TargetDurationYears)
}

type RiskMonitorPolicy struct {
	InvestmentGradeOrdinalMin int
	DistressRatingOrdinalMax  int
	MajorDowngradeSteps       int
}

var DefaultRiskMonitorPolicy = RiskMonitorPolicy{
	InvestmentGradeOrdinalMin: 3,
	DistressRatingOrdinalMax:  -4,
	MajorDowngradeSteps:       3,
}

type BondSelectionContext struct {
	Profile        RiskProfile
	HorizonDate    time.Time
	PurchaseDate   time.Time
	BudgetRub      *float64
	APITradeOnly   bool
}

type RiskSnapshot struct {
	HasDefault          bool
	HasTechnicalDefault bool
	CreditRating        *string
}
