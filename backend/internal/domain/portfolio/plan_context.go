package portfolio

// PlanMode distinguishes simulation vs live trading plan builds.
type PlanMode string

const (
	PlanModeSimulation PlanMode = "simulation"
	PlanModeTrading    PlanMode = "trading"
)

// PlanContext carries mode-specific inputs for a unified BuildPlan entry.
type PlanContext struct {
	Mode                 PlanMode
	Positions            []PortfolioPosition
	HistoricalEvents     []CashflowEvent
	BrokerCashRub        float64
	InvestedCapitalRub   float64
	SimulationInitialRub float64
	AssumeBestPutOutcome bool
}

func (c PlanContext) IsTrading() bool {
	return c.Mode == PlanModeTrading
}

func (c PlanContext) journalInitialCash() float64 {
	if c.IsTrading() {
		return 0
	}
	return c.SimulationInitialRub
}

func (c PlanContext) forwardInitialCash() float64 {
	if c.IsTrading() {
		return c.BrokerCashRub
	}
	return c.SimulationInitialRub
}

func (c PlanContext) investedBaseline() float64 {
	if c.IsTrading() {
		return c.InvestedCapitalRub
	}
	return c.SimulationInitialRub
}

// NewSimulationPlanContext builds plan inputs for simulation mode.
func NewSimulationPlanContext(p Portfolio, assumeBestPutOutcome bool) PlanContext {
	return PlanContext{
		Mode:                 PlanModeSimulation,
		Positions:            p.Positions,
		SimulationInitialRub: p.InitialAmountRub,
		AssumeBestPutOutcome: assumeBestPutOutcome,
	}
}
