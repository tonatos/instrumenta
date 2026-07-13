package portfolio

import (
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

// BuyAllocation is one buy when deploying available cash.
type BuyAllocation struct {
	ISIN               string
	FIGI               *string
	Name               string
	Lots               int
	SuggestedPricePct  float64
	EstimatedAmountRub float64
	IsExistingPosition bool
}

func applyDurationGuardrail(bs []bonds.BondRecord, dp DurationPolicy, notes *[]string) []bonds.BondRecord {
	limit := dp.MaxWeightedDurationYears
	if limit == nil {
		return bs
	}
	var kept []bonds.BondRecord
	for _, b := range bs {
		d := RateSensitiveDuration(b, dp)
		if d == nil || *d <= *limit {
			kept = append(kept, b)
		}
	}
	dropped := len(bs) - len(kept)
	if dropped > 0 {
		*notes = append(*notes, fmt.Sprintf(
			"Гардрейл по дюрации: исключено %d бумаг(и) с дюрацией > %.1f г.",
			dropped, *limit,
		))
	}
	return kept
}

func AutoCompose(
	initialAmount float64,
	universe []bonds.BondRecord,
	profile RiskProfile,
	horizonDate, today time.Time,
	keyRate, taxRate float64,
	apiTradeOnly bool,
	dp DurationPolicy,
) (positions []PortfolioPosition, leftoverCash float64, notes []string) {
	if initialAmount <= 0 {
		return nil, 0, []string{"Бюджет ≤ 0 — нечего распределять"}
	}
	ctx := SelectionContext(profile, horizonDate, today, apiTradeOnly, nil)
	selection := SelectRankedBonds(universe, ctx, DefaultBondSelectionPolicy, keyRate, taxRate, dp, nil)
	scored := applyDurationGuardrail(selection.Bonds, dp, &notes)
	if len(scored) == 0 {
		msg := "Под выбранный профиль и горизонт не нашлось ни одной подходящей бумаги. "
		if apiTradeOnly {
			msg += "Попробуйте отключить фильтр «только API-торгуемые» или расширьте горизонт / смягчите профиль."
		} else {
			msg += "Расширьте горизонт, смягчите профиль или обновите данные MOEX."
		}
		return nil, initialAmount, []string{msg}
	}
	if selection.FallbackNote != "" {
		notes = append(notes, selection.FallbackNote)
	}
	targetCount := maxInt(MinAutoPositions, minInt(MaxAutoPositions, int(mathRound(1/TargetPositionShare))))
	targetPerPosition := initialAmount / float64(targetCount)
	maxPerPosition := initialAmount * MaxPositionShare
	minPerPosition := maxFloat(MinPositionAmountRub, initialAmount*MinPositionShare)

	remaining := initialAmount
	type lotState struct {
		bond bonds.BondRecord
		lots int
		cost float64
	}
	bought := make(map[string]*lotState)

	for _, bond := range scored {
		if remaining < minPerPosition || len(positions) >= targetCount {
			break
		}
		lotCost := 0.0
		if p := bond.PricePerLotRub(); p != nil {
			lotCost = *p
		}
		if lotCost <= 0 {
			continue
		}
		targetLots := maxInt(1, int(mathRound(targetPerPosition/lotCost)))
		costAtTarget := float64(targetLots) * lotCost
		if lotCost > maxPerPosition {
			continue
		}
		if costAtTarget < minPerPosition {
			targetLots = int(minPerPosition/lotCost) + 1
			costAtTarget = float64(targetLots) * lotCost
			if costAtTarget > maxPerPosition || costAtTarget > remaining {
				continue
			}
		}
		if costAtTarget > maxPerPosition {
			targetLots = int(maxPerPosition / lotCost)
			costAtTarget = float64(targetLots) * lotCost
		}
		if costAtTarget > remaining {
			targetLots = int(remaining / lotCost)
			costAtTarget = float64(targetLots) * lotCost
		}
		if targetLots < 1 || costAtTarget < minPerPosition {
			continue
		}
		positions = append(positions, PositionFromBond(bond, targetLots, today, PositionSourceInitial))
		bought[bond.ISIN] = &lotState{bond: bond, lots: targetLots, cost: costAtTarget}
		remaining -= costAtTarget
	}

	if remaining >= minPerPosition {
		changed := true
		for changed && remaining > 0 {
			changed = false
			for _, bond := range scored {
				state, ok := bought[bond.ISIN]
				if !ok {
					continue
				}
				lotCost := 0.0
				if p := state.bond.PricePerLotRub(); p != nil {
					lotCost = *p
				}
				if lotCost <= 0 || lotCost > remaining {
					continue
				}
				if state.cost+lotCost > maxPerPosition {
					continue
				}
				state.lots++
				state.cost += lotCost
				remaining -= lotCost
				changed = true
				if remaining < lotCost {
					break
				}
			}
		}
		for i := range positions {
			if state, ok := bought[positions[i].ISIN]; ok && state.lots != positions[i].Lots {
				positions[i].Lots = state.lots
				positions[i].PurchaseAmountRub = positions[i].PurchaseDirtyPriceRub * float64(state.lots*positions[i].LotSize)
			}
		}
	}

	if len(positions) < MinAutoPositions && remaining >= minPerPosition {
		for _, bond := range scored {
			if _, ok := bought[bond.ISIN]; ok {
				continue
			}
			lotCost := 0.0
			if p := bond.PricePerLotRub(); p != nil {
				lotCost = *p
			}
			if lotCost <= 0 || lotCost > remaining || lotCost > maxPerPosition {
				continue
			}
			maxLots := minInt(int(remaining/lotCost), int(maxPerPosition/lotCost))
			if maxLots < 1 {
				continue
			}
			cost := float64(maxLots) * lotCost
			if cost < minPerPosition {
				continue
			}
			positions = append(positions, PositionFromBond(bond, maxLots, today, PositionSourceInitial))
			bought[bond.ISIN] = &lotState{bond: bond, lots: maxLots, cost: cost}
			remaining -= cost
			if len(positions) >= MinAutoPositions || remaining < minPerPosition {
				break
			}
		}
	}

	if len(positions) == 0 {
		notes = append(notes, fmt.Sprintf(
			"Не нашлось бумаг, помещающихся в правила диверсификации (одна позиция должна быть не меньше %s ₽ и не больше %s ₽). Увеличьте бюджет или смягчите профиль.",
			formatShare(minPerPosition, initialAmount), formatShare(maxPerPosition, initialAmount),
		))
	} else {
		notes = append(notes, fmt.Sprintf(
			"Распределение: %d позиций по ~%s бюджета каждая (потолок %.0f%%, минимум %s ₽).",
			len(positions), formatShare(targetPerPosition, initialAmount), MaxPositionShare*100,
			fmt.Sprintf("%.0f", minPerPosition),
		))
		if remaining >= minPerPosition {
			notes = append(notes, fmt.Sprintf(
				"Остаток %.0f ₽ не вложен — недостаточно для очередной позиции по правилам диверсификации.",
				remaining,
			))
		}
	}
	return positions, remaining, notes
}

func formatShare(value, total float64) string {
	if total <= 0 {
		return fmt.Sprintf("%.0f ₽", value)
	}
	return fmt.Sprintf("%.0f%% (%.0f ₽)", value/total*100, value)
}

func mathRound(v float64) float64 {
	if v < 0 {
		return float64(int(v - 0.5))
	}
	return float64(int(v + 0.5))
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxFloat(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

func SweepRemainingCash(
	remainingCashRub float64,
	currentLotsByISIN map[string]int,
	universe []bonds.BondRecord,
	profile RiskProfile,
	horizonDate, asOfDate time.Time,
	keyRate, taxRate float64,
	apiTradeOnly bool,
	accountKind *AccountKind,
	dp DurationPolicy,
	totalBudgetRub float64,
) ([]BuyAllocation, []string) {
	var notes []string
	if remainingCashRub <= 0 {
		return nil, notes
	}
	ctx := SelectionContext(profile, horizonDate, asOfDate, apiTradeOnly, nil)
	scored := SelectRankedBonds(universe, ctx, DefaultBondSelectionPolicy, keyRate, taxRate, dp, nil).Bonds
	scored = applyDurationGuardrail(scored, dp, &notes)
	if len(scored) == 0 {
		return nil, notes
	}
	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, b := range universe {
		universeByISIN[b.ISIN] = b
	}
	maxPerPosition := totalBudgetRub * MaxPositionShare
	buffer := BuyLimitPriceBuffer(accountKind)
	allocations := make(map[string]BuyAllocation)
	remaining := remainingCashRub
	currentCost := make(map[string]float64)
	for isin, lots := range currentLotsByISIN {
		if bond, ok := universeByISIN[isin]; ok {
			if p := bond.PricePerLotRub(); p != nil {
				currentCost[isin] = float64(lots) * *p
			}
		}
	}
	changed := true
	for changed && remaining > 0 {
		changed = false
		for _, bond := range scored {
			lotCost := 0.0
			if p := bond.PricePerLotRub(); p != nil {
				lotCost = *p
			}
			if lotCost <= 0 || remaining+0.01 < lotCost {
				continue
			}
			if currentCost[bond.ISIN]+lotCost > maxPerPosition+0.01 {
				continue
			}
			lastPrice := 100.0
			if bond.LastPrice != nil {
				lastPrice = *bond.LastPrice
			}
			if existing, ok := allocations[bond.ISIN]; ok {
				existing.Lots++
				existing.EstimatedAmountRub += lotCost
				allocations[bond.ISIN] = existing
			} else {
				figi := bond.FIGI
				var figiPtr *string
				if figi != "" {
					figiPtr = &figi
				}
				allocations[bond.ISIN] = BuyAllocation{
					ISIN: bond.ISIN, FIGI: figiPtr, Name: bond.Name, Lots: 1,
					SuggestedPricePct: float64(SuggestedBuyLimitPricePct(lastPrice, buffer)),
					EstimatedAmountRub: lotCost, IsExistingPosition: currentLotsByISIN[bond.ISIN] > 0,
				}
			}
			currentCost[bond.ISIN] += lotCost
			remaining -= lotCost
			changed = true
			break
		}
	}
	if remainingCashRub-remaining > 0 {
		notes = append(notes, fmt.Sprintf("Добор остатка: вложено ещё %.0f ₽.", remainingCashRub-remaining))
	}
	out := make([]BuyAllocation, 0, len(allocations))
	for _, a := range allocations {
		out = append(out, a)
	}
	return out, notes
}

func ComposeBuyAllocations(
	totalBudgetRub, cashToDeployRub float64,
	currentLotsByISIN map[string]int,
	universe []bonds.BondRecord,
	profile RiskProfile,
	horizonDate, today time.Time,
	keyRate, taxRate float64,
	apiTradeOnly bool,
	accountKind *AccountKind,
	dp DurationPolicy,
) ([]BuyAllocation, []string) {
	if cashToDeployRub <= 0 {
		return nil, []string{"Сумма к развёртыванию ≤ 0 — нечего распределять."}
	}
	existingISINs := make(map[string]struct{})
	for isin := range currentLotsByISIN {
		existingISINs[isin] = struct{}{}
	}
	existingCount := len(existingISINs)
	newSlots := maxInt(0, MaxAutoPositions-existingCount)
	var notes []string
	deployUniverse := universe
	if existingCount >= MaxAutoPositions {
		deployUniverse = topScoredExistingBonds(universe, existingISINs, profile, horizonDate, today, keyRate, taxRate, apiTradeOnly, dp)
		notes = append(notes, "Лимит 10 позиций — докупаем только существующие бумаги.")
	}
	targetPositions, _, composeNotes := AutoCompose(totalBudgetRub, deployUniverse, profile, horizonDate, today, keyRate, taxRate, apiTradeOnly, dp)
	notes = append(notes, composeNotes...)
	if len(targetPositions) == 0 {
		return nil, append(notes, "Кэш не распределён: не удалось построить целевую структуру.")
	}
	targetLots := make(map[string]int)
	var targetOrder []string
	for _, p := range targetPositions {
		targetLots[p.ISIN] = p.Lots
		targetOrder = append(targetOrder, p.ISIN)
	}
	universeByISIN := make(map[string]bonds.BondRecord)
	for _, b := range universe {
		universeByISIN[b.ISIN] = b
	}
	currentLots := make(map[string]int)
	for k, v := range currentLotsByISIN {
		currentLots[k] = v
	}
	var allocations []BuyAllocation
	remaining := cashToDeployRub
	buffer := BuyLimitPriceBuffer(accountKind)

	allocate := func(isin string, target int) {
		if remaining <= 0 {
			return
		}
		bond, ok := universeByISIN[isin]
		if !ok {
			return
		}
		lotCost := 0.0
		if p := bond.PricePerLotRub(); p != nil {
			lotCost = *p
		}
		if lotCost <= 0 {
			return
		}
		needed := maxInt(0, target-currentLots[isin])
		if needed < 1 {
			return
		}
		lots := minInt(needed, int(remaining/lotCost))
		if lots < 1 {
			return
		}
		cost := float64(lots) * lotCost
		lastPrice := 100.0
		if bond.LastPrice != nil {
			lastPrice = *bond.LastPrice
		}
		var figiPtr *string
		if bond.FIGI != "" {
			figiPtr = &bond.FIGI
		}
		_, existed := currentLotsByISIN[isin]
		allocations = append(allocations, BuyAllocation{
			ISIN: isin, FIGI: figiPtr, Name: bond.Name, Lots: lots,
			SuggestedPricePct: float64(SuggestedBuyLimitPricePct(lastPrice, buffer)),
			EstimatedAmountRub: cost, IsExistingPosition: existed,
		})
		currentLots[isin] += lots
		remaining -= cost
	}

	var newTargets, existingTargets []string
	for _, isin := range targetOrder {
		if _, ok := existingISINs[isin]; ok {
			existingTargets = append(existingTargets, isin)
		} else {
			newTargets = append(newTargets, isin)
		}
	}
	if len(newTargets) > newSlots {
		newTargets = newTargets[:newSlots]
	}
	for _, isin := range newTargets {
		allocate(isin, targetLots[isin])
	}
	for _, isin := range existingTargets {
		allocate(isin, targetLots[isin])
	}
	if len(allocations) == 0 {
		return nil, append(notes, "Кэш не распределён: нет подходящих бумаг или сумма слишком мала.")
	}
	distributed := cashToDeployRub - remaining
	notes = append(notes, fmt.Sprintf(
		"Распределено %.0f ₽ из %.0f ₽ по %d бумагам. Остаток: %.0f ₽.",
		distributed, cashToDeployRub, len(allocations), remaining,
	))
	return allocations, notes
}

func topScoredExistingBonds(
	universe []bonds.BondRecord,
	existing map[string]struct{},
	profile RiskProfile,
	horizonDate, today time.Time,
	keyRate, taxRate float64,
	apiTradeOnly bool,
	dp DurationPolicy,
) []bonds.BondRecord {
	ctx := SelectionContext(profile, horizonDate, today, apiTradeOnly, nil)
	scored := SelectRankedBonds(universe, ctx, DefaultBondSelectionPolicy, keyRate, taxRate, dp, nil).Bonds
	var result []bonds.BondRecord
	for _, bond := range scored {
		if _, ok := existing[bond.ISIN]; !ok {
			continue
		}
		result = append(result, bond)
		if len(result) >= MaxAutoPositions {
			break
		}
	}
	return result
}
