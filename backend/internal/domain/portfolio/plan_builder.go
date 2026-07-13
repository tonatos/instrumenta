package portfolio

import (
	"math"
	"sort"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

const maxPlanXIRRPct = 200.0

var onAccountSources = map[PositionSourceType]bool{
	PositionSourceInitial: true,
	PositionSourceAdopted: true,
}

func planInitialCash(p Portfolio, accountMoneyRub *float64) float64 {
	if accountMoneyRub != nil {
		return *accountMoneyRub
	}
	return p.InitialAmountRub
}

func investedCapitalBaseline(p Portfolio, accountMoneyRub *float64) float64 {
	if accountMoneyRub == nil {
		return p.InitialAmountRub
	}
	deployed := 0.0
	for _, position := range OpenPositions(p.Positions) {
		deployed += PositionCostBasis(position)
	}
	return deployed + *accountMoneyRub
}

type cashflowFlow struct {
	date   time.Time
	amount float64
}

func planXIRRCAGRFallback(finalValue, invested float64, horizonDays int) *float64 {
	if horizonDays <= 0 || invested <= 0 || finalValue <= 0 {
		return nil
	}
	growth := finalValue / invested
	annualReturn := math.Pow(growth, 365.0/float64(horizonDays)) - 1
	v := round2(annualReturn * 100)
	return &v
}

func calculatePlanExpectedXIRR(
	plan *PortfolioPlan,
	today time.Time,
	investedBaseline float64,
	accountMoneyRub *float64,
	horizonDays int,
) *float64 {
	horizon := plan.Portfolio.HorizonDate
	if horizonDays <= 0 || investedBaseline <= 0 || plan.FinalPortfolioValueRub <= 0 {
		return nil
	}
	var cashflow []cashflowFlow
	if accountMoneyRub != nil {
		deployedOutflow := 0.0
		for _, position := range OpenPositions(plan.Portfolio.Positions) {
			if !onAccountSources[position.Source] {
				continue
			}
			cost := PositionCostBasis(position)
			if cost > 0 && !position.PurchaseDate.After(horizon) {
				cashflow = append(cashflow, cashflowFlow{position.PurchaseDate, -cost})
				deployedOutflow += cost
			}
		}
		cashGap := investedBaseline - deployedOutflow
		if cashGap > 0 {
			cashflow = append(cashflow, cashflowFlow{today, -cashGap})
		}
	} else {
		cashflow = append(cashflow, cashflowFlow{today, -investedBaseline})
	}
	cashflow = append(cashflow, cashflowFlow{horizon, plan.FinalPortfolioValueRub})

	hasPositive, hasNegative := false, false
	for _, f := range cashflow {
		if f.amount > 0 {
			hasPositive = true
		}
		if f.amount < 0 {
			hasNegative = true
		}
	}
	if !hasPositive || !hasNegative {
		return planXIRRCAGRFallback(plan.FinalPortfolioValueRub, investedBaseline, horizonDays)
	}
	rate := xirr(cashflow)
	if rate == nil {
		return planXIRRCAGRFallback(plan.FinalPortfolioValueRub, investedBaseline, horizonDays)
	}
	xirrPct := *rate * 100
	if math.Abs(xirrPct) > maxPlanXIRRPct {
		plan.Notes = append(plan.Notes, "Прогнозная XIRR нестабильна при коротком горизонте — показана упрощённая CAGR-оценка.")
		return planXIRRCAGRFallback(plan.FinalPortfolioValueRub, investedBaseline, horizonDays)
	}
	v := round2(xirrPct)
	return &v
}

func xirr(flows []cashflowFlow) *float64 {
	if len(flows) < 2 {
		return nil
	}
	guess := 0.1
	for iter := 0; iter < 50; iter++ {
		f, df := 0.0, 0.0
		t0 := flows[0].date
		for _, fl := range flows {
			years := fl.date.Sub(t0).Hours() / 24 / 365
			denom := math.Pow(1+guess, years)
			if denom == 0 {
				return nil
			}
			f += fl.amount / denom
			df -= years * fl.amount / (denom * (1 + guess))
		}
		if math.Abs(f) < 1e-7 {
			return &guess
		}
		if df == 0 {
			break
		}
		guess -= f / df
	}
	return nil
}

// BuildPlan constructs a cashflow plan through event-sourced simulation.
func BuildPlan(
	p Portfolio,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	accountSnapshotMoneyRub *float64,
	assumeBestPutOutcome bool,
	durationPolicy DurationPolicy,
) PortfolioPlan {
	horizon := p.HorizonDate
	initialCash := planInitialCash(p, accountSnapshotMoneyRub)
	sim := RunSimulation(
		p, universe, today, horizon, keyRate, taxRate, initialCash,
		accountSnapshotMoneyRub, assumeBestPutOutcome, durationPolicy,
	)
	plan := PortfolioPlan{Portfolio: p, InitialCashRub: sim.InitialCashRub}
	plan.Events = MergeCashflowEvents(sim.Events)
	plan.AllPositions = sim.AllPositions
	plan.HeldPositions = sim.HeldPositions
	plan.UpcomingPutOffers = sim.UpcomingPutOffers
	plan.Notes = append([]string(nil), sim.Notes...)
	plan.ResolvedSlots = MergeReinvestmentSlots(sim.ResolvedSlots)

	for i := range plan.ResolvedSlots {
		plan.ResolvedSlots[i].ExpectedCashRub = RunningCashBeforePurchase(
			plan.Events, plan.ResolvedSlots[i].PurchaseDate(), plan.InitialCashRub,
		)
	}
	for i, slot := range plan.ResolvedSlots {
		plan.ResolvedSlots[i] = EnrichReinvestmentSlot(slot, p, universe, keyRate, taxRate)
	}

	universeByISIN := make(map[string]bonds.BondRecord)
	for _, b := range universe {
		universeByISIN[b.ISIN] = b
	}
	finalizePlanTotals(&plan, universeByISIN, today, taxRate, accountSnapshotMoneyRub, durationPolicy)
	buildValueTimeline(&plan, today, assumeBestPutOutcome, accountSnapshotMoneyRub)
	if PruneStaleSlotOverrides(&p, plan.ResolvedSlots) {
		p.Touch()
	}
	plan.Portfolio = p
	return plan
}

func weightedYTM(positions []PortfolioPosition, universeByISIN map[string]bonds.BondRecord) *float64 {
	var weightTotal, weightedSum float64
	for _, position := range positions {
		bond, ok := universeByISIN[position.ISIN]
		if !ok || bond.YTMNet == nil {
			continue
		}
		weight := position.PurchaseAmountRub
		weightTotal += weight
		weightedSum += weight * *bond.YTMNet
	}
	if weightTotal <= 0 {
		return nil
	}
	v := weightedSum / weightTotal
	return &v
}

func finalizePlanTotals(
	plan *PortfolioPlan,
	universeByISIN map[string]bonds.BondRecord,
	today time.Time,
	taxRate float64,
	accountMoneyRub *float64,
	durationPolicy DurationPolicy,
) {
	p := plan.Portfolio
	cash := planInitialCash(p, accountMoneyRub)
	initialSpent := 0.0
	if accountMoneyRub != nil {
		for _, position := range OpenPositions(p.Positions) {
			if onAccountSources[position.Source] && !position.PurchaseDate.After(p.HorizonDate) {
				initialSpent += position.PurchaseAmountRub
			}
		}
	}
	totalInvested := initialSpent
	totalCouponNet, totalRedemption := 0.0, 0.0
	for _, event := range plan.Events {
		cash += event.AmountRub
		switch event.Kind {
		case "purchase":
			totalInvested += -event.AmountRub
		case "coupon":
			totalCouponNet += event.AmountRub
		case "maturity", "put_offer":
			totalRedemption += event.AmountRub
		}
	}
	afterTax := 1 - taxRate
	totalCouponGross := totalCouponNet
	if afterTax > 0 {
		totalCouponGross = totalCouponNet / afterTax
	}
	priceTax := 0.0
	for _, position := range plan.AllPositions {
		gain := PriceGainTotal(position)
		if gain > 0 {
			priceTax += gain * taxRate
		}
	}
	heldValue := 0.0
	for _, h := range plan.HeldPositions {
		heldValue += h.EstimatedValueRub
	}
	finalValue := cash + heldValue
	investedBaseline := investedCapitalBaseline(p, accountMoneyRub)

	plan.TotalInvestedRub = round2(totalInvested)
	plan.TotalCouponNetRub = round2(totalCouponNet)
	plan.TotalCouponGrossRub = round2(totalCouponGross)
	plan.TotalTaxRub = round2(totalCouponGross-totalCouponNet + priceTax)
	plan.TotalRedemptionRub = round2(totalRedemption)
	plan.FinalCashBalanceRub = round2(cash)
	plan.HeldPositionsValueRub = round2(heldValue)
	plan.FinalPortfolioValueRub = round2(finalValue)
	plan.InvestedCapitalRub = round2(investedBaseline)
	plan.TotalNetProfitRub = round2(plan.FinalCashBalanceRub - investedBaseline)
	plan.TotalNetProfitWithHeldRub = round2(plan.FinalPortfolioValueRub - investedBaseline)

	if w := weightedYTM(OpenPositions(p.Positions), universeByISIN); w != nil {
		v := round2(*w)
		plan.WeightedYTMNetPct = &v
	}
	if w := WeightedDurationByPurchase(OpenPositions(p.Positions), universeByISIN, durationPolicy); w != nil {
		v := round2(*w)
		plan.WeightedDurationYears = &v
	}
	if w := weightedYTM(plan.AllPositions, universeByISIN); w != nil {
		v := round2(*w)
		plan.WeightedYTMNetFullPct = &v
	}
	if plan.WeightedYTMNetPct != nil && plan.WeightedYTMNetFullPct != nil &&
		*plan.WeightedYTMNetPct > 0 && *plan.WeightedYTMNetFullPct < *plan.WeightedYTMNetPct*0.7 {
		dilution := (1 - *plan.WeightedYTMNetFullPct/ *plan.WeightedYTMNetPct) * 100
		plan.Notes = append(plan.Notes, "YTM реинвестиций ниже YTM текущих позиций — разбавление ~"+itoa(int(dilution))+"%.")
	}
	horizonDays := shared.DaysBetween(today, p.HorizonDate)
	if horizonDays < 0 {
		horizonDays = 0
	}
	plan.HorizonDays = horizonDays
	plan.EffectiveAnnualReturnPct = calculatePlanExpectedXIRR(plan, today, investedBaseline, accountMoneyRub, horizonDays)
}

func positionRedemptionGross(position PortfolioPosition, isPut bool) float64 {
	if isPut {
		pricePct := 100.0
		if position.OfferPricePct != nil {
			pricePct = *position.OfferPricePct
		}
		return position.FaceValue * (pricePct / 100) * float64(position.BondsCount())
	}
	return position.FaceValue * float64(position.BondsCount())
}

func positionIsPutAtEnd(position PortfolioPosition, endDate *time.Time, today time.Time) bool {
	return endDate != nil && position.OfferDate != nil &&
		endDate.Equal(*position.OfferDate) &&
		!PutOfferSubmissionClosed(position, today)
}

func positionMarketValueAt(
	position PortfolioPosition,
	asOf, horizon, today time.Time,
	heldByID map[int64]HeldPositionAtHorizon,
	assumeBestPutOutcome bool,
) float64 {
	if asOf.Before(position.PurchaseDate) {
		return 0
	}
	endDate := PositionEndDate(position, horizon, today, assumeBestPutOutcome)
	isPut := positionIsPutAtEnd(position, endDate, today)
	purchaseValue := position.PurchaseAmountRub
	if endDate != nil && !endDate.After(asOf) && !endDate.After(horizon) {
		return 0
	}
	var terminalValue float64
	var terminalDate time.Time
	if endDate == nil || endDate.After(horizon) {
		if held, ok := heldByID[position.ID]; ok {
			terminalValue = held.EstimatedValueRub
		} else {
			terminalValue = position.FaceValue * float64(position.BondsCount())
		}
		terminalDate = horizon
	} else {
		terminalValue = positionRedemptionGross(position, isPut)
		terminalDate = *endDate
	}
	if !asOf.Before(terminalDate) {
		if endDate != nil && endDate.After(horizon) {
			return terminalValue
		}
		return 0
	}
	spanDays := shared.DaysBetween(position.PurchaseDate, terminalDate)
	if spanDays <= 0 {
		return purchaseValue
	}
	progress := float64(shared.DaysBetween(position.PurchaseDate, asOf)) / float64(spanDays)
	return purchaseValue + (terminalValue-purchaseValue)*progress
}

func buildValueTimeline(
	plan *PortfolioPlan,
	today time.Time,
	assumeBestPutOutcome bool,
	accountMoneyRub *float64,
) {
	p := plan.Portfolio
	horizon := p.HorizonDate
	if today.After(horizon) {
		plan.ValueTimeline = nil
		return
	}
	initialCash := planInitialCash(p, accountMoneyRub)
	heldByID := make(map[int64]HeldPositionAtHorizon)
	for _, h := range plan.HeldPositions {
		heldByID[h.Position.ID] = h
	}
	keyDates := map[string]time.Time{
		today.Format("2006-01-02"): today,
		horizon.Format("2006-01-02"): horizon,
	}
	for _, event := range plan.Events {
		if !event.Date.Before(today) && !event.Date.After(horizon) {
			keyDates[event.Date.Format("2006-01-02")] = event.Date
		}
	}
	for _, position := range plan.AllPositions {
		if !position.PurchaseDate.Before(today) && !position.PurchaseDate.After(horizon) {
			keyDates[position.PurchaseDate.Format("2006-01-02")] = position.PurchaseDate
		}
		if end := PositionEndDate(position, horizon, today, assumeBestPutOutcome); end != nil &&
			!end.Before(today) && !end.After(horizon) {
			keyDates[end.Format("2006-01-02")] = *end
		}
	}
	var dates []time.Time
	for _, d := range keyDates {
		dates = append(dates, d)
	}
	sort.Slice(dates, func(i, j int) bool { return dates[i].Before(dates[j]) })
	sortedEvents := append([]CashflowEvent(nil), plan.Events...)
	sort.Slice(sortedEvents, func(i, j int) bool {
		di, si := JournalSortKey(sortedEvents[i])
		dj, sj := JournalSortKey(sortedEvents[j])
		if di.Equal(dj) {
			return si < sj
		}
		return di.Before(dj)
	})
	for _, pointDate := range dates {
		cash := initialCash
		for _, event := range sortedEvents {
			if event.Date.After(pointDate) {
				break
			}
			cash += event.AmountRub
		}
		positionsValue := 0.0
		for _, position := range plan.AllPositions {
			positionsValue += positionMarketValueAt(position, pointDate, horizon, today, heldByID, assumeBestPutOutcome)
		}
		plan.ValueTimeline = append(plan.ValueTimeline, PortfolioValuePoint{
			Date: pointDate, CashRub: round2(cash), PositionsValueRub: round2(positionsValue),
			TotalValueRub: round2(cash + positionsValue),
		})
	}
}