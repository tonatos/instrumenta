package trading

import (
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

const minBuyCashRub = 5_000.0
const reinvestWatchDays = 14

// AttachPreviewValidation is soft validation before attaching a broker account.
type AttachPreviewValidation struct {
	CanAttach                 bool
	Blockers                  []string
	Warnings                  []string
	EffectiveInitialAmountRub float64
}

// TradingAdvice is the full advisory response for the UI.
type TradingAdvice struct {
	Holdings               []HoldingView
	Cashflow               []portfolio.CashflowEvent
	Performance            *ActualPerformance
	Suggestions            []Suggestion
	ActiveOrders           []BrokerActiveOrder
	MoneyRub               float64
	AvailableMoneyRub      float64
	BlockedMoneyRub        float64
	Warnings               []string
	AsOf                   string
	WeightedDurationYears  *float64
	DeploySession          *DeploySession
}

func universeByFIGI(universe []bonds.BondRecord) map[string]bonds.BondRecord {
	result := make(map[string]bonds.BondRecord)
	for _, bond := range universe {
		if bond.FIGI != "" {
			result[bond.FIGI] = bond
		}
	}
	return result
}

func universeByISIN(universe []bonds.BondRecord) map[string]bonds.BondRecord {
	result := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		result[bond.ISIN] = bond
	}
	return result
}

func holdingMarketValue(
	brokerLots, lotSize int,
	currentPricePct *shared.PriceUnitPct,
	currentNKDRub *shared.Rub,
	faceValue float64,
) *float64 {
	if currentPricePct == nil {
		return nil
	}
	cleanPerBond := float64(*currentPricePct) / 100 * faceValue
	nkd := 0.0
	if currentNKDRub != nil {
		nkd = float64(*currentNKDRub)
	}
	quantity := brokerLots * lotSize
	v := (cleanPerBond + nkd) * float64(quantity)
	return &v
}

// BuildHoldings assembles holdings from broker snapshot and market universe.
func BuildHoldings(snapshot BrokerSnapshot, universe []bonds.BondRecord) []HoldingView {
	byFIGI := universeByFIGI(universe)
	var holdings []HoldingView
	for figi, pos := range snapshot.BondPositions {
		if pos.Lots <= 0 {
			continue
		}
		bond, ok := byFIGI[figi]
		name := pos.Ticker
		isin := ""
		lotSize := max(1, pos.Quantity/max(1, pos.Lots))
		var ytm, marketValue *float64
		var maturityDate, offerDate *time.Time
		if ok {
			name = bond.Name
			isin = bond.ISIN
			lotSize = bond.LotSize
			ytm = bond.YTM
			maturityDate = bond.MaturityDate
			offerDate = bond.OfferDate
			face := bond.FaceValue
			if face <= 0 {
				face = 1000
			}
			marketValue = holdingMarketValue(pos.Lots, lotSize, pos.CurrentPricePct, pos.CurrentNKDRub, face)
		}
		var currentPct, nkd *float64
		if pos.CurrentPricePct != nil {
			v := float64(*pos.CurrentPricePct)
			currentPct = &v
		}
		if pos.CurrentNKDRub != nil {
			v := float64(*pos.CurrentNKDRub)
			nkd = &v
		}
		holdings = append(holdings, HoldingView{
			FIGI: figi, ISIN: isin, Name: name, Lots: pos.Lots, Quantity: pos.Quantity,
			LotSize: lotSize, CurrentPricePct: currentPct, CurrentNKDRub: nkd, YTM: ytm,
			MaturityDate: maturityDate, OfferDate: offerDate, MarketValueRub: marketValue,
		})
	}
	sortHoldingsByName(holdings)
	return holdings
}

func sortHoldingsByName(holdings []HoldingView) {
	for i := 0; i < len(holdings); i++ {
		for j := i + 1; j < len(holdings); j++ {
			if holdings[j].Name < holdings[i].Name {
				holdings[i], holdings[j] = holdings[j], holdings[i]
			}
		}
	}
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// HoldingISINsFromSnapshot returns ISINs held on the account.
func HoldingISINsFromSnapshot(snapshot BrokerSnapshot, universe []bonds.BondRecord) map[string]struct{} {
	result := make(map[string]struct{})
	for _, h := range BuildHoldings(snapshot, universe) {
		if h.ISIN != "" {
			result[h.ISIN] = struct{}{}
		}
	}
	return result
}

func applyAveragePurchasePrice(position *portfolio.PortfolioPosition, averagePricePct float64) {
	cleanPct := averagePricePct
	dirtyPerBond := cleanPct/100*position.FaceValue + position.PurchaseACIRub
	position.PurchaseCleanPricePct = cleanPct
	position.PurchaseDirtyPriceRub = dirtyPerBond
	position.PurchaseAmountRub = dirtyPerBond * float64(position.BondsCount())
}

// HoldingsToPositions builds ephemeral plan positions from holdings.
func HoldingsToPositions(
	holdings []HoldingView,
	universeByISIN map[string]bonds.BondRecord,
	purchaseDate time.Time,
	averagePricePctByFIGI map[string]float64,
) []portfolio.PortfolioPosition {
	var positions []portfolio.PortfolioPosition
	for _, holding := range holdings {
		bond, ok := universeByISIN[holding.ISIN]
		if !ok {
			continue
		}
		position := portfolio.PositionFromBond(bond, holding.Lots, purchaseDate, portfolio.PositionSourceAdopted)
		position.FIGI = &holding.FIGI
		portfolio.SyncPutOfferFromBond(&position, bond)
		if avg, ok := averagePricePctByFIGI[holding.FIGI]; ok {
			applyAveragePurchasePrice(&position, avg)
		}
		positions = append(positions, position)
	}
	return positions
}

// EffectiveTradingPositions returns adopted broker holdings plus pending INITIAL plan lots.
func EffectiveTradingPositions(
	p portfolio.Portfolio,
	snapshot BrokerSnapshot,
	universe []bonds.BondRecord,
	purchaseDate time.Time,
) []portfolio.PortfolioPosition {
	universeByISIN := universeByISIN(universe)
	holdings := BuildHoldings(snapshot, universe)
	avgByFIGI := make(map[string]float64)
	for figi, pos := range snapshot.BondPositions {
		if pos.AveragePricePct != nil {
			avgByFIGI[figi] = float64(*pos.AveragePricePct)
		}
	}
	adopted := HoldingsToPositions(holdings, universeByISIN, purchaseDate, avgByFIGI)
	adoptedISINs := make(map[string]struct{})
	for _, pos := range adopted {
		adoptedISINs[pos.ISIN] = struct{}{}
	}
	var pending []portfolio.PortfolioPosition
	for _, pos := range p.Positions {
		if pos.Source == portfolio.PositionSourceInitial {
			if _, ok := adoptedISINs[pos.ISIN]; !ok {
				pending = append(pending, pos)
			}
		}
	}
	return append(adopted, pending...)
}

// BuildHoldingsCashflow forecasts coupon and redemption cashflows for held positions.
func BuildHoldingsCashflow(positions []portfolio.PortfolioPosition, horizonDate, today time.Time) []portfolio.CashflowEvent {
	var events []portfolio.CashflowEvent
	for _, position := range positions {
		end := portfolio.PositionEndDate(position, horizonDate, today, false)
		if end == nil {
			continue
		}
		for _, couponDate := range portfolio.CouponDatesInRange(position, *end) {
			if !couponDate.After(today) {
				continue
			}
			amount := portfolio.CouponPaymentPerEvent(position)
			if amount <= 0 {
				continue
			}
			bondsCount := position.BondsCount()
			lots := position.Lots
			isin := position.ISIN
			events = append(events, portfolio.CashflowEvent{
				Date: couponDate, Kind: "coupon", AmountRub: amount,
				Description: portfolio.CashflowEventDescription("coupon", position.Name, &bondsCount, &lots, ""),
				RelatedISIN: &isin, IsProjected: true, Lots: &lots, BondsCount: &bondsCount,
			})
		}
		if end.After(today) {
			kind := "maturity"
			if position.OfferDate != nil && position.OfferDate.Equal(*end) {
				kind = "put_offer"
			}
			redemption := position.FaceValue * float64(position.BondsCount())
			bondsCount := position.BondsCount()
			lots := position.Lots
			isin := position.ISIN
			events = append(events, portfolio.CashflowEvent{
				Date: *end, Kind: kind, AmountRub: redemption,
				Description: portfolio.CashflowEventDescription(kind, position.Name, &bondsCount, &lots, ""),
				RelatedISIN: &isin, IsProjected: true, Lots: &lots, BondsCount: &bondsCount,
			})
		}
	}
	sortCashflow(events)
	return events
}

func sortCashflow(events []portfolio.CashflowEvent) {
	for i := 0; i < len(events); i++ {
		for j := i + 1; j < len(events); j++ {
			ki0, ki1 := portfolio.EventSortKey(events[i])
			kj0, kj1 := portfolio.EventSortKey(events[j])
			if kj0.Before(ki0) || (kj0.Equal(ki0) && kj1 < ki1) {
				events[i], events[j] = events[j], events[i]
			}
		}
	}
}

func holdingsDeployedValue(holdings []HoldingView, universeByISIN map[string]bonds.BondRecord) float64 {
	total := 0.0
	for _, holding := range holdings {
		if holding.MarketValueRub != nil {
			total += *holding.MarketValueRub
			continue
		}
		if bond, ok := universeByISIN[holding.ISIN]; ok {
			if p := bond.PricePerLotRub(); p != nil && *p > 0 {
				total += float64(holding.Lots) * *p
			}
		}
	}
	return total
}

// BuildBuySuggestions recommends deploying free cash into the portfolio strategy.
func BuildBuySuggestions(
	p portfolio.Portfolio,
	holdings []HoldingView,
	universe []bonds.BondRecord,
	availableCash float64,
	today time.Time,
	keyRate, taxRate float64,
	durationPolicy portfolio.DurationPolicy,
) []Suggestion {
	if availableCash < minBuyCashRub {
		return nil
	}
	currentLots := make(map[string]int)
	for _, h := range holdings {
		if h.ISIN != "" {
			currentLots[h.ISIN] = h.Lots
		}
	}
	allocations, _, notes := portfolio.DeployCash(
		availableCash, currentLots, universe, p.RiskProfile, p.HorizonDate, today,
		keyRate, taxRate, p.APITradeOnly, p.AccountKind, durationPolicy, nil, portfolio.PositionSourceReinvestMaturity,
	)
	if len(allocations) == 0 {
		return nil
	}
	baseReason := "Свободный кэш на счёте — рекомендуем докупить по стратегии портфеля"
	noteSuffix := ""
	if len(notes) > 0 {
		noteSuffix = " (" + notes[len(notes)-1] + ")"
	}
	universeMap := universeByISIN(universe)
	var suggestions []Suggestion
	for _, allocation := range allocations {
		var marketPrice *float64
		if bond, ok := universeMap[allocation.ISIN]; ok && bond.LastPrice != nil {
			marketPrice = bond.LastPrice
		}
		price := allocation.SuggestedPricePct
		suggestions = append(suggestions, Suggestion{
			ID: StableID(p.ID, "buy", allocation.ISIN),
			Kind: SuggestionKindBuy, ISIN: allocation.ISIN, Name: allocation.Name,
			Lots: allocation.Lots, FIGI: allocation.FIGI,
			SuggestedPricePct: &price, MarketPricePct: marketPrice,
			Reason: baseReason + noteSuffix,
		})
	}
	return suggestions
}

// BuildReinvestSuggestions returns actionable reinvest suggestions after due date.
func BuildReinvestSuggestions(
	p portfolio.Portfolio,
	positions []portfolio.PortfolioPosition,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	policy portfolio.BondSelectionPolicy,
	planning portfolio.PlanningPolicy,
	durationPolicy portfolio.DurationPolicy,
) []Suggestion {
	return buildReinvestSuggestionsForPositions(
		p, positions, universe, today, keyRate, taxRate, policy, planning, durationPolicy, true,
	)
}

// BuildReinvestWatchSuggestions returns informational reinvest watches before due date.
func BuildReinvestWatchSuggestions(
	p portfolio.Portfolio,
	positions []portfolio.PortfolioPosition,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	policy portfolio.BondSelectionPolicy,
	planning portfolio.PlanningPolicy,
	durationPolicy portfolio.DurationPolicy,
) []Suggestion {
	return buildReinvestSuggestionsForPositions(
		p, positions, universe, today, keyRate, taxRate, policy, planning, durationPolicy, false,
	)
}

func buildReinvestSuggestionsForPositions(
	p portfolio.Portfolio,
	positions []portfolio.PortfolioPosition,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	policy portfolio.BondSelectionPolicy,
	planning portfolio.PlanningPolicy,
	durationPolicy portfolio.DurationPolicy,
	actionableOnly bool,
) []Suggestion {
	var suggestions []Suggestion
	horizon := p.HorizonDate
	for _, position := range positions {
		end := portfolio.PositionEndDate(position, horizon, today, false)
		if end == nil {
			continue
		}
		daysUntil := shared.DaysBetween(today, *end)
		if daysUntil > reinvestWatchDays {
			continue
		}
		if actionableOnly {
			if daysUntil > 0 {
				continue
			}
		} else if daysUntil <= 0 {
			continue
		}
		expectedCash := position.FaceValue * float64(position.BondsCount())
		reinvestDate := shared.AddDays(*end, planning.ReinvestmentGapDays)
		if reinvestDate.After(horizon) {
			continue
		}
		ctx := portfolio.BondSelectionContext{
			Profile: p.RiskProfile, HorizonDate: horizon, PurchaseDate: reinvestDate,
			BudgetRub: &expectedCash, APITradeOnly: p.APITradeOnly,
		}
		selection := portfolio.SelectRankedBonds(universe, ctx, policy, keyRate, taxRate, durationPolicy, nil)
		if len(selection.Bonds) == 0 {
			continue
		}
		replacement := selection.Bonds[0]
		marketPrice := replacement.LastPrice
		basePrice := 100.0
		if marketPrice != nil {
			basePrice = *marketPrice
		}
		buffer := BuyLimitPriceBuffer(p.AccountKind)
		pricePct := float64(SuggestedBuyLimitPricePct(basePrice, buffer))
		var urgency SuggestionUrgency
		var kind SuggestionKind
		var reason, suggestionID string
		if actionableOnly {
			urgency = SuggestionUrgencySoon
			if daysUntil < 0 {
				urgency = SuggestionUrgencyCritical
			}
			kind = SuggestionKindReinvest
			reason = fmt.Sprintf(
				"Погашение %s %s (≈%s ₽) — рекомендуем реинвестировать",
				position.Name, shared.FormatDate(end), shared.FormatNumber(expectedCash, 0),
			)
			suggestionID = StableID(p.ID, "reinvest", position.ISIN+":"+shared.FormatISODate(*end))
		} else {
			urgency = SuggestionUrgencyNormal
			kind = SuggestionKindReinvestWatch
			reason = fmt.Sprintf(
				"Погашение %s %s (≈%s ₽) — подготовьте реинвестицию",
				position.Name, shared.FormatDate(end), shared.FormatNumber(expectedCash, 0),
			)
			suggestionID = StableID(p.ID, "reinvest-watch", position.ISIN+":"+shared.FormatISODate(*end))
		}
		var figi *string
		if replacement.FIGI != "" {
			figi = &replacement.FIGI
		}
		suggestions = append(suggestions, Suggestion{
			ID: suggestionID, Kind: kind, ISIN: replacement.ISIN, Name: replacement.Name,
			Lots: position.Lots, FIGI: figi, SuggestedPricePct: &pricePct, MarketPricePct: marketPrice,
			Reason: reason, DueDate: end, SourceISIN: &position.ISIN, Urgency: urgency,
		})
	}
	return suggestions
}

// CollectAccountWarnings returns soft warnings when viewing or attaching an account.
func CollectAccountWarnings(
	snapshot BrokerSnapshot,
	universeByISIN map[string]bonds.BondRecord,
	holdings []HoldingView,
) []string {
	var warnings []string
	if snapshot.HasForeignInstruments() {
		warnings = append(warnings, "На счёте есть инструменты, не относящиеся к облигациям RUB.")
	}
	knownFIGIs := make(map[string]struct{})
	for _, bond := range universeByISIN {
		if bond.FIGI != "" {
			knownFIGIs[bond.FIGI] = struct{}{}
		}
	}
	for _, holding := range holdings {
		if holding.FIGI != "" {
			if _, ok := knownFIGIs[holding.FIGI]; !ok && holding.ISIN == "" {
				warnings = append(warnings, fmt.Sprintf("Позиция %s (%s) не найдена в рыночном универсе.", holding.Name, holding.FIGI))
			}
		}
	}
	return warnings
}

// ValidateAttachSoft allows attaching any account with warnings instead of blockers.
func ValidateAttachSoft(snapshot BrokerSnapshot, p portfolio.Portfolio, universe []bonds.BondRecord) AttachPreviewValidation {
	universeByISIN := universeByISIN(universe)
	holdings := BuildHoldings(snapshot, universe)
	warnings := CollectAccountWarnings(snapshot, universeByISIN, holdings)
	if len(snapshot.BondPositions) > 0 {
		warnings = append(warnings, "На счёте уже есть облигации — рекомендации строятся от фактических позиций.")
	}
	deployed := holdingsDeployedValue(holdings, universeByISIN)
	effective := p.InitialAmountRub
	if v := float64(snapshot.MoneyRub) + deployed; v > effective {
		effective = v
	}
	return AttachPreviewValidation{
		CanAttach: true, Warnings: warnings, EffectiveInitialAmountRub: effective,
	}
}

// AdviseParams groups optional advisory inputs.
type AdviseParams struct {
	KeyRate           float64
	TaxRate           float64
	Today             *time.Time
	SelectionPolicy   portfolio.BondSelectionPolicy
	PlanningPolicy    portfolio.PlanningPolicy
	DurationPolicy    portfolio.DurationPolicy
	RiskPolicy        portfolio.RiskMonitorPolicy
	ActiveSession     *DeploySession
}

// Advise builds the full trading advisory response.
func Advise(
	p portfolio.Portfolio,
	snapshot BrokerSnapshot,
	activeOrders []BrokerActiveOrder,
	operations []BrokerOperation,
	universe []bonds.BondRecord,
	params AdviseParams,
) TradingAdvice {
	asOf := time.Now().UTC()
	today := asOf
	if params.Today != nil {
		today = shared.DateOnly(*params.Today)
	}
	selectionPolicy := params.SelectionPolicy
	if selectionPolicy.MinCleanPricePct == 0 && selectionPolicy.MinReplacementHorizonDays == 0 {
		selectionPolicy = portfolio.DefaultBondSelectionPolicy
	}
	planningPolicy := params.PlanningPolicy
	if planningPolicy.ReinvestmentGapDays == 0 {
		planningPolicy = portfolio.DefaultPlanningPolicy
	}
	durationPolicy := params.DurationPolicy
	riskPolicy := params.RiskPolicy
	if riskPolicy.InvestmentGradeOrdinalMin == 0 && riskPolicy.MajorDowngradeSteps == 0 {
		riskPolicy = portfolio.DefaultRiskMonitorPolicy
	}

	holdings := BuildHoldings(snapshot, universe)
	positions := EffectiveTradingPositions(p, snapshot, universe, today)
	cashflow := BuildHoldingsCashflow(positions, p.HorizonDate, today)

	perfPortfolio := p
	perfPortfolio.Positions = positions
	performance := SummarizeActualPerformance(perfPortfolio, snapshot, operations, asOf)

	available := float64(snapshot.AvailableMoneyRub())
	var sessionForAdvice *DeploySession
	var buySuggestions, reinvestSuggestions []Suggestion
	if params.ActiveSession != nil && IsSessionActive(*params.ActiveSession, &asOf) {
		session := SyncSessionWithOrders(*params.ActiveSession, activeOrders)
		session = ApplySessionStaleness(session, universe, p, DefaultDeploySessionPolicy(), &asOf)
		if IsSessionActive(session, &asOf) {
			sessionForAdvice = &session
			buySuggestions = SessionItemsToSuggestions(session, universe, map[DeploySessionItemKind]bool{DeploySessionItemBuy: true})
			reinvestSuggestions = SessionItemsToSuggestions(session, universe, map[DeploySessionItemKind]bool{DeploySessionItemReinvest: true})
		} else {
			buySuggestions = BuildBuySuggestions(p, holdings, universe, available, today, params.KeyRate, params.TaxRate, durationPolicy)
			reinvestSuggestions = BuildReinvestSuggestions(
				p, positions, universe, today, params.KeyRate, params.TaxRate, selectionPolicy, planningPolicy, durationPolicy,
			)
		}
	} else {
		buySuggestions = BuildBuySuggestions(p, holdings, universe, available, today, params.KeyRate, params.TaxRate, durationPolicy)
		reinvestSuggestions = BuildReinvestSuggestions(
			p, positions, universe, today, params.KeyRate, params.TaxRate, selectionPolicy, planningPolicy, durationPolicy,
		)
	}
	reinvestWatch := BuildReinvestWatchSuggestions(
		p, positions, universe, today, params.KeyRate, params.TaxRate, selectionPolicy, planningPolicy, durationPolicy,
	)
	notifPolicy := notifications.NotificationPolicy{IncludePutOfferWatchInAlerts: true}
	alertSuggestions := AlertsToSuggestions(notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: p, Holdings: holdingSnapshots(holdings), Positions: positions,
		Universe: universe, Today: today, NotificationPolicy: notifPolicy, RiskPolicy: riskPolicy,
	}))
	suggestions := append(append(append(buySuggestions, reinvestSuggestions...), reinvestWatch...), alertSuggestions...)
	warnings := CollectAccountWarnings(snapshot, universeByISIN(universe), holdings)
	durationHoldings := make([]portfolio.DurationHolding, len(holdings))
	for i, h := range holdings {
		durationHoldings[i] = portfolio.DurationHolding{ISIN: h.ISIN, MarketValueRub: h.MarketValueRub}
	}
	weightedDur := portfolio.WeightedDurationByMarket(durationHoldings, universeByISIN(universe), durationPolicy)
	var weightedRounded *float64
	if weightedDur != nil {
		v := round2(*weightedDur)
		weightedRounded = &v
	}
	return TradingAdvice{
		Holdings: holdings, Cashflow: cashflow, Performance: &performance, Suggestions: suggestions,
		ActiveOrders: append([]BrokerActiveOrder(nil), activeOrders...),
		MoneyRub: float64(snapshot.MoneyRub), AvailableMoneyRub: available,
		BlockedMoneyRub: float64(snapshot.BlockedMoneyRub), Warnings: warnings,
		AsOf: asOf.Format(time.RFC3339), WeightedDurationYears: weightedRounded, DeploySession: sessionForAdvice,
	}
}

func holdingSnapshots(holdings []HoldingView) []notifications.HoldingSnapshot {
	out := make([]notifications.HoldingSnapshot, len(holdings))
	for i, h := range holdings {
		out[i] = notifications.HoldingSnapshot{
			ISIN: h.ISIN, FIGI: h.FIGI, Name: h.Name, Lots: h.Lots, CurrentPricePct: h.CurrentPricePct,
		}
	}
	return out
}
