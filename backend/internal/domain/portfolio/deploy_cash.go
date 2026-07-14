package portfolio

import (
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

// MaxAffordableLots returns max lots fitting budget with dirty-price accounting.
func MaxAffordableLots(
	b bonds.BondRecord,
	budgetRub float64,
	purchaseDate time.Time,
	source PositionSourceType,
) int {
	lotCost := 0.0
	if p := b.PricePerLotRub(); p != nil {
		lotCost = *p
	}
	if lotCost <= 0 || budgetRub+0.01 < lotCost {
		return 0
	}
	lots := int(budgetRub / lotCost)
	for lots > 0 {
		phantom := PositionFromBond(b, lots, purchaseDate, source)
		if phantom.PurchaseAmountRub <= budgetRub+0.01 {
			return lots
		}
		lots--
	}
	return 0
}

func positionsToAllocations(
	targetPositions []PortfolioPosition,
	universeByISIN map[string]bonds.BondRecord,
	existingISINs map[string]struct{},
	accountKind *AccountKind,
) []BuyAllocation {
	buffer := BuyLimitPriceBuffer(accountKind)
	var allocations []BuyAllocation
	for _, position := range targetPositions {
		bond, ok := universeByISIN[position.ISIN]
		if !ok || position.Lots < 1 {
			continue
		}
		lastPrice := 100.0
		if bond.LastPrice != nil {
			lastPrice = *bond.LastPrice
		}
		var figiPtr *string
		if bond.FIGI != "" {
			figiPtr = &bond.FIGI
		}
		_, existed := existingISINs[position.ISIN]
		allocations = append(allocations, BuyAllocation{
			ISIN:               position.ISIN,
			FIGI:               figiPtr,
			Name:               bond.Name,
			Lots:               position.Lots,
			SuggestedPricePct:  float64(SuggestedBuyLimitPricePct(lastPrice, buffer)),
			EstimatedAmountRub: position.PurchaseAmountRub,
			IsExistingPosition: existed,
		})
	}
	return allocations
}

func mergeAllocationLots(allocations []BuyAllocation) []BuyAllocation {
	merged := make(map[string]BuyAllocation)
	var order []string
	for _, item := range allocations {
		existing, ok := merged[item.ISIN]
		if !ok {
			merged[item.ISIN] = item
			order = append(order, item.ISIN)
			continue
		}
		merged[item.ISIN] = BuyAllocation{
			ISIN:               existing.ISIN,
			FIGI:               existing.FIGI,
			Name:               existing.Name,
			Lots:               existing.Lots + item.Lots,
			SuggestedPricePct:  existing.SuggestedPricePct,
			EstimatedAmountRub: existing.EstimatedAmountRub + item.EstimatedAmountRub,
			IsExistingPosition: existing.IsExistingPosition || item.IsExistingPosition,
		}
	}
	out := make([]BuyAllocation, 0, len(order))
	for _, isin := range order {
		out = append(out, merged[isin])
	}
	return out
}

func lotsAfterAllocations(base map[string]int, allocations []BuyAllocation) map[string]int {
	out := make(map[string]int, len(base))
	for k, v := range base {
		out[k] = v
	}
	for _, a := range allocations {
		out[a.ISIN] = out[a.ISIN] + a.Lots
	}
	return out
}

func sumAllocationAmount(allocations []BuyAllocation) float64 {
	var total float64
	for _, a := range allocations {
		total += a.EstimatedAmountRub
	}
	return total
}

// DeployCash deploys all available cash — unified entry for plan and advisory.
func DeployCash(
	cashRub float64,
	currentLotsByISIN map[string]int,
	universe []bonds.BondRecord,
	profile RiskProfile,
	horizonDate, asOfDate time.Time,
	keyRate, taxRate float64,
	apiTradeOnly bool,
	accountKind *AccountKind,
	dp DurationPolicy,
	confirmedISIN *string,
	reinvestSource PositionSourceType,
) (allocations []BuyAllocation, remaining float64, notes []string) {
	if cashRub <= 0 {
		return nil, 0, []string{"Сумма к развёртыванию ≤ 0 — нечего распределять."}
	}

	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		universeByISIN[bond.ISIN] = bond
	}
	existingISINs := make(map[string]struct{})
	for isin := range currentLotsByISIN {
		existingISINs[isin] = struct{}{}
	}

	if confirmedISIN != nil {
		bond, ok := universeByISIN[*confirmedISIN]
		if !ok || !HasUsablePrice(bond) {
			return nil, cashRub, []string{
				fmt.Sprintf("Бумага %s недоступна или без рыночной цены.", *confirmedISIN),
			}
		}
		if invalid := ValidateReplacementBond(bond, asOfDate, horizonDate); invalid != nil {
			return nil, cashRub, []string{fmt.Sprintf("Подтверждённая замена отклонена: %s", *invalid)}
		}
		lots := MaxAffordableLots(bond, cashRub, asOfDate, reinvestSource)
		if lots < 1 {
			return nil, cashRub, []string{"Недостаточно кэша на 1 лот подтверждённой замены."}
		}
		phantom := PositionFromBond(bond, lots, asOfDate, reinvestSource)
		buffer := BuyLimitPriceBuffer(accountKind)
		lastPrice := 100.0
		if bond.LastPrice != nil {
			lastPrice = *bond.LastPrice
		}
		spent := phantom.PurchaseAmountRub
		remaining = cashRub - spent
		if remaining < 0 {
			remaining = 0
		}
		var figiPtr *string
		if bond.FIGI != "" {
			figiPtr = &bond.FIGI
		}
		_, existed := existingISINs[bond.ISIN]
		allocations = []BuyAllocation{{
			ISIN:               bond.ISIN,
			FIGI:               figiPtr,
			Name:               bond.Name,
			Lots:               lots,
			SuggestedPricePct:  float64(SuggestedBuyLimitPricePct(lastPrice, buffer)),
			EstimatedAmountRub: spent,
			IsExistingPosition: existed,
		}}
		if remaining > 0 {
			updatedLots := make(map[string]int)
			for k, v := range currentLotsByISIN {
				updatedLots[k] = v
			}
			updatedLots[bond.ISIN] = updatedLots[bond.ISIN] + lots
			extra, rem2, extraNotes := DeployCash(
				remaining, updatedLots, universe, profile, horizonDate, asOfDate,
				keyRate, taxRate, apiTradeOnly, accountKind, dp, nil, reinvestSource,
			)
			notes = append(notes, extraNotes...)
			allocations = mergeAllocationLots(append(allocations, extra...))
			remaining = rem2
		}
		notes = append(notes, fmt.Sprintf("Распределено %.0f ₽ из %.0f ₽.", cashRub-remaining, cashRub))
		return allocations, remaining, notes
	}

	if len(existingISINs) >= MaxAutoPositions {
		var holdingsValue float64
		for isin, lots := range currentLotsByISIN {
			if bond, ok := universeByISIN[isin]; ok {
				if p := bond.PricePerLotRub(); p != nil {
					holdingsValue += *p * float64(lots)
				}
			}
		}
		allocations, composeNotes := ComposeBuyAllocations(
			holdingsValue+cashRub, cashRub, currentLotsByISIN, universe, profile,
			horizonDate, asOfDate, keyRate, taxRate, apiTradeOnly, accountKind, dp,
			&DefaultDiversificationPolicy,
		)
		notes = append(notes, composeNotes...)
		spent := sumAllocationAmount(allocations)
		remaining = cashRub - spent
		if remaining < 0 {
			remaining = 0
		}
		if remaining > 0 {
			swept, sweepNotes := SweepRemainingCash(
				remaining,
				lotsAfterAllocations(currentLotsByISIN, allocations),
				universe, profile, horizonDate, asOfDate, keyRate, taxRate,
				apiTradeOnly, accountKind, dp, holdingsValue+cashRub,
			)
			notes = append(notes, sweepNotes...)
			allocations = mergeAllocationLots(append(allocations, swept...))
			spent = sumAllocationAmount(allocations)
			remaining = cashRub - spent
			if remaining < 0 {
				remaining = 0
			}
		}
		notes = append(notes, fmt.Sprintf(
			"Распределено %.0f ₽ из %.0f ₽ по %d бумагам. Остаток: %.0f ₽.",
			cashRub-remaining, cashRub, len(allocations), remaining,
		))
		return allocations, remaining, notes
	}

	targetPositions, leftover, composeNotes := AutoCompose(
		cashRub, universe, profile, horizonDate, asOfDate, keyRate, taxRate, apiTradeOnly, dp,
		&DefaultDiversificationPolicy, currentLotsByISIN,
	)
	notes = append(notes, composeNotes...)
	allocations = positionsToAllocations(targetPositions, universeByISIN, existingISINs, accountKind)
	remaining = leftover
	if remaining > 0 && len(allocations) > 0 {
		swept, sweepNotes := SweepRemainingCash(
			remaining,
			lotsAfterAllocations(currentLotsByISIN, allocations),
			universe, profile, horizonDate, asOfDate, keyRate, taxRate,
			apiTradeOnly, accountKind, dp, cashRub,
		)
		notes = append(notes, sweepNotes...)
		allocations = mergeAllocationLots(append(allocations, swept...))
		spent := sumAllocationAmount(allocations)
		remaining = cashRub - spent
		if remaining < 0 {
			remaining = 0
		}
	}

	if len(allocations) == 0 {
		return nil, cashRub, append(notes, "Кэш не распределён: не удалось построить целевую структуру.")
	}
	notes = append(notes, fmt.Sprintf(
		"Распределено %.0f ₽ из %.0f ₽ по %d бумагам. Остаток: %.0f ₽.",
		cashRub-remaining, cashRub, len(allocations), remaining,
	))
	return allocations, remaining, notes
}
