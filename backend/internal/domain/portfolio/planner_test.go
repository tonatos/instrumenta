package portfolio_test

import (
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

func TestValidateReplacementBondRejectsMaturityBeforePurchase(t *testing.T) {
	bond := makeBond("RU0001", "Test", shared.MustParseDate("2026-06-01"), 99, 18, 80, bonds.BoolPtr(true), nil)
	reason := portfolio.ValidateReplacementBond(bond, shared.MustParseDate("2027-01-01"), shared.MustParseDate("2027-06-01"))
	if reason == nil {
		t.Fatal("expected rejection")
	}
}

func TestValidateReplacementBondAcceptsValid(t *testing.T) {
	bond := makeBond("RU0002", "Valid", shared.MustParseDate("2027-03-01"), 99, 18, 80, bonds.BoolPtr(true), nil)
	reason := portfolio.ValidateReplacementBond(bond, shared.MustParseDate("2026-06-01"), shared.MustParseDate("2027-06-01"))
	if reason != nil {
		t.Fatalf("unexpected rejection: %s", *reason)
	}
}

func TestAutoComposeDiversifies(t *testing.T) {
	today := shared.MustParseDate("2026-01-01")
	horizon := shared.MustParseDate("2027-01-01")
	maturities := []time.Time{
		shared.MustParseDate("2026-03-01"), shared.MustParseDate("2026-05-01"),
		shared.MustParseDate("2026-07-01"), shared.MustParseDate("2026-09-01"),
		shared.MustParseDate("2026-11-01"), shared.MustParseDate("2027-01-01"),
		shared.MustParseDate("2027-03-01"),
	}
	var universe []bonds.BondRecord
	for i, m := range maturities {
		isin := "RU000" + string(rune('0'+i+1))
		universe = append(universe, makeBond(isin, "Bond", m, 99, 18, 80-float64(i), bonds.BoolPtr(true), nil))
	}
	positions, cash, _ := portfolio.AutoCompose(
		400_000, universe, portfolio.RiskProfileNormal, horizon, today, 14.5, 0.13, true, portfolio.DefaultDurationPolicy,
		&portfolio.DefaultDiversificationPolicy, nil,
	)
	if len(positions) < 1 {
		t.Fatal("expected positions")
	}
	if cash < 0 {
		t.Fatalf("negative cash: %v", cash)
	}
}

func TestAutoComposeExcludesDistressedBonds(t *testing.T) {
	today := shared.MustParseDate("2026-01-01")
	horizon := shared.MustParseDate("2027-01-01")
	distressed := makeBond("RU000DST", "Distressed", shared.MustParseDate("2026-09-01"), 75, 35, 95, bonds.BoolPtr(true), nil)
	quality := makeBond("RU000QAL", "Quality", shared.MustParseDate("2026-09-01"), 99, 16, 70, bonds.BoolPtr(true), nil)
	positions, _, _ := portfolio.AutoCompose(
		200_000, []bonds.BondRecord{distressed, quality}, portfolio.RiskProfileAggressive, horizon, today, 14.5, 0.13, false, portfolio.DefaultDurationPolicy,
		&portfolio.DefaultDiversificationPolicy, nil,
	)
	if len(positions) == 0 {
		t.Fatal("expected at least one position")
	}
	for _, p := range positions {
		if p.ISIN == distressed.ISIN {
			t.Fatal("distressed bond must be excluded")
		}
	}
}

func TestSameDayMaturityBeforeDeployPurchase(t *testing.T) {
	deployDate := shared.MustParseDate("2026-11-21")
	lots, bondsCount := 1, 1
	isin := "RU000B1"
	events := []portfolio.CashflowEvent{
		{Date: deployDate, Kind: "coupon", AmountRub: 5, Description: "c", RelatedISIN: &isin, JournalSeq: 1},
		{Date: deployDate, Kind: "maturity", AmountRub: 418, Description: "m", RelatedISIN: bonds.StrPtr("RU000A1"), JournalSeq: 2},
		{Date: deployDate, Kind: "purchase", AmountRub: -400, Description: "p", RelatedISIN: &isin, JournalSeq: 3, Lots: &lots, BondsCount: &bondsCount},
	}
	rows := portfolio.CashflowRowsWithBalance(events, 100)
	for _, row := range rows {
		if row.BalanceAfterRub < -0.01 {
			t.Fatalf("negative balance: %+v", row)
		}
	}
	if rows[len(rows)-1].BalanceAfterRub != 123 {
		t.Fatalf("expected 123, got %v", rows[len(rows)-1].BalanceAfterRub)
	}
}

func TestAA19dfdLivePlanBalance(t *testing.T) {
	p := aa19dfdLivePortfolio()
	today := shared.MustParseDate("2026-07-10")
	cash := p.CashBalanceRub
	historical, _, _ := trading.ReconcileCashToBroker(nil, today, cash)
	plan := portfolio.BuildPlan(p, aa19dfdLiveUniverse(), today, 16, 0.13, portfolio.PlanContext{
		Mode: portfolio.PlanModeTrading, Positions: p.Positions, HistoricalEvents: historical,
		BrokerCashRub: cash, InvestedCapitalRub: portfolio.InvestedCapitalFromPositions(p.Positions, shared.Rub(cash)),
		AssumeBestPutOutcome: false,
	}, portfolio.DefaultDurationPolicy)
	rows := portfolio.CashflowRowsWithBalance(plan.Events, plan.InitialCashRub)
	for _, row := range rows {
		if row.BalanceAfterRub < -0.01 {
			t.Fatalf("negative API balance: %+v", row)
		}
	}
}

func TestAA19dfdFirstReinvestSlotBudgetAndOverride(t *testing.T) {
	const sourceISIN = "RU000A100PB0"
	const targetISIN = "RU000A109TG2" // iКарРус1P4

	p := aa19dfdLivePortfolio()
	today := shared.MustParseDate("2026-07-10")
	cash := p.CashBalanceRub
	historical, _, _ := trading.ReconcileCashToBroker(nil, today, cash)
	planCtx := portfolio.PlanContext{
		Mode: portfolio.PlanModeTrading, Positions: p.Positions, HistoricalEvents: historical,
		BrokerCashRub: cash, InvestedCapitalRub: portfolio.InvestedCapitalFromPositions(p.Positions, shared.Rub(cash)),
		AssumeBestPutOutcome: false,
	}
	universe := aa19dfdLiveUniverse()

	plan := portfolio.BuildPlan(p, universe, today, 16, 0.13, planCtx, portfolio.DefaultDurationPolicy)
	slot := findReinvestSlot(plan.ResolvedSlots, sourceISIN)
	if slot == nil {
		t.Fatal("expected reinvest slot for ЖКХРСЯ")
	}
	if slot.ExpectedCashRub <= 0 {
		t.Fatalf("expected positive slot budget, got %.2f", slot.ExpectedCashRub)
	}
	if reason := portfolio.ValidateSlotReplacement(p, universe, *slot, targetISIN); reason != nil {
		t.Fatalf("iКарРус1P4 override should pass: %s", *reason)
	}

	// Same PlanContext as GET /plan and POST /slots/override (trading, assumeBestPutOutcome=false).
	validationPlan := portfolio.BuildPlan(p, universe, today, 16, 0.13, planCtx, portfolio.DefaultDurationPolicy)
	validationSlot := findReinvestSlot(validationPlan.ResolvedSlots, sourceISIN)
	if validationSlot == nil {
		t.Fatal("validation plan missing slot")
	}
	if validationSlot.ExpectedCashRub != slot.ExpectedCashRub {
		t.Fatalf("plan vs override budget mismatch: %.2f vs %.2f",
			slot.ExpectedCashRub, validationSlot.ExpectedCashRub)
	}

	// Regression: old simulation path with InitialAmountRub produced negative budget.
	simCtx := portfolio.NewSimulationPlanContext(p, true)
	simPlan := portfolio.BuildPlan(p, universe, today, 16, 0.13, simCtx, portfolio.DefaultDurationPolicy)
	simSlot := findReinvestSlot(simPlan.ResolvedSlots, sourceISIN)
	if simSlot != nil && simSlot.ExpectedCashRub >= 0 {
		t.Fatalf("expected negative budget on legacy simulation path, got %.2f", simSlot.ExpectedCashRub)
	}
}

func TestAA19dfdTradingInvestedCapitalNotInflated(t *testing.T) {
	p := aa19dfdLivePortfolio()
	today := shared.MustParseDate("2026-07-10")
	cash := p.CashBalanceRub
	historical, _, _ := trading.ReconcileCashToBroker(nil, today, cash)
	invested := portfolio.InvestedCapitalFromPositions(p.Positions, shared.Rub(cash))
	plan := portfolio.BuildPlan(p, aa19dfdLiveUniverse(), today, 16, 0.13, portfolio.PlanContext{
		Mode: portfolio.PlanModeTrading, Positions: p.Positions, HistoricalEvents: historical,
		BrokerCashRub: cash, InvestedCapitalRub: invested, AssumeBestPutOutcome: false,
	}, portfolio.DefaultDurationPolicy)
	if plan.InvestedCapitalRub > 280_000 {
		t.Fatalf("invested capital inflated to %.2f (double-count regression)", plan.InvestedCapitalRub)
	}
	if plan.InvestedCapitalRub < invested-1 || plan.InvestedCapitalRub > invested+1 {
		t.Fatalf("plan invested %.2f != baseline %.2f", plan.InvestedCapitalRub, invested)
	}
	if plan.EffectiveAnnualReturnPct != nil && *plan.EffectiveAnnualReturnPct < -50 {
		t.Fatalf("forecast XIRR unexpectedly negative: %.2f", *plan.EffectiveAnnualReturnPct)
	}
}

func findReinvestSlot(slots []portfolio.ReinvestmentSlot, sourceISIN string) *portfolio.ReinvestmentSlot {
	for i := range slots {
		if slots[i].SourcePositionISIN != nil && *slots[i].SourcePositionISIN == sourceISIN {
			return &slots[i]
		}
	}
	return nil
}

func TestAA19dfdTradingCashflowNonNegative(t *testing.T) {
	p := aa19dfdPortfolio()
	p.Mode = portfolio.PortfolioModeTrading
	plan := portfolio.BuildPlan(p, aa19dfdUniverse(), shared.MustParseDate("2026-07-10"), 16, 0.13, portfolio.NewSimulationPlanContext(p, false), portfolio.DefaultDurationPolicy)
	rows := portfolio.CashflowRowsWithBalance(plan.Events, plan.InitialCashRub)
	for _, row := range rows {
		if row.BalanceAfterRub < -0.01 {
			t.Fatalf("negative balance: %+v", row)
		}
	}
}

func TestCouponScheduleUsesNextCouponAnchor(t *testing.T) {
	next := shared.MustParseDate("2026-07-28")
	period := 91
	rate := 23.0
	pos := portfolio.PortfolioPosition{
		PurchaseDate: shared.MustParseDate("2026-07-07"), CouponRate: &rate,
		CouponPeriodDays: &period, NextCouponDate: &next, FaceValue: 1000, Lots: 5, LotSize: 1,
	}
	dates := portfolio.CouponDatesInRange(pos, shared.MustParseDate("2026-07-28"))
	if len(dates) == 0 {
		t.Fatal("expected coupon on maturity-aligned date")
	}
}

func TestInvestedCapitalSimulationMode(t *testing.T) {
	p := portfolio.Portfolio{InitialAmountRub: 100_000, Mode: portfolio.PortfolioModeSimulation}
	if v := portfolio.InvestedCapitalRub(p, nil); v != 100_000 {
		t.Fatalf("expected 100000, got %v", v)
	}
}

func TestEmptySimulationPortfolioPlanHasNoPhantomCompose(t *testing.T) {
	today := shared.MustParseDate("2026-07-14")
	horizon := shared.MustParseDate("2027-07-14")
	universe := []bonds.BondRecord{
		makeBond("RU0001", "Bond A", shared.MustParseDate("2027-03-01"), 99, 18, 80, bonds.BoolPtr(true), nil),
		makeBond("RU0002", "Bond B", shared.MustParseDate("2027-05-01"), 99, 17, 75, bonds.BoolPtr(true), nil),
	}
	p := portfolio.Portfolio{
		InitialAmountRub: 400_000,
		HorizonDate:      horizon,
		RiskProfile:      portfolio.RiskProfileNormal,
		CashBalanceRub:   400_000,
		Mode:             portfolio.PortfolioModeSimulation,
		APITradeOnly:     true,
	}

	plan := portfolio.BuildPlan(p, universe, today, 16, 0.13, portfolio.NewSimulationPlanContext(p, true), portfolio.DefaultDurationPolicy)

	if len(plan.Events) != 0 {
		t.Fatalf("expected no cashflow events, got %d", len(plan.Events))
	}
	if plan.FinalPortfolioValueRub != 400_000 {
		t.Fatalf("expected flat final value 400000, got %v", plan.FinalPortfolioValueRub)
	}
	if plan.TotalNetProfitRub != 0 {
		t.Fatalf("expected zero profit, got %v", plan.TotalNetProfitRub)
	}
	if plan.EffectiveAnnualReturnPct != nil && *plan.EffectiveAnnualReturnPct != 0 {
		t.Fatalf("expected zero XIRR, got %v", *plan.EffectiveAnnualReturnPct)
	}
	if len(plan.AllPositions) != 0 {
		t.Fatalf("expected no phantom positions, got %d", len(plan.AllPositions))
	}
}
