package portfolio

import (
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

// RateSensitiveDuration returns duration for rate-risk (floaters ≈ policy floater years).
func RateSensitiveDuration(b bonds.BondRecord, dp DurationPolicy) *float64 {
	if b.IsFloatingCoupon() {
		v := dp.FloaterRateDurationYears
		return &v
	}
	return b.DurationYears()
}

// DurationHolding is weighted by market value for duration metrics.
type DurationHolding struct {
	ISIN            string
	MarketValueRub  *float64
}

func WeightedDurationByPurchase(
	positions []PortfolioPosition,
	universeByISIN map[string]bonds.BondRecord,
	durationPolicy DurationPolicy,
) *float64 {
	var weightTotal, weightedSum float64
	for _, pos := range positions {
		bond, ok := universeByISIN[pos.ISIN]
		if !ok {
			continue
		}
		duration := RateSensitiveDuration(bond, durationPolicy)
		if duration == nil {
			continue
		}
		weight := pos.PurchaseAmountRub
		weightTotal += weight
		weightedSum += weight * *duration
	}
	if weightTotal <= 0 {
		return nil
	}
	v := weightedSum / weightTotal
	return &v
}

func WeightedDurationByMarket(
	holdings []DurationHolding,
	universeByISIN map[string]bonds.BondRecord,
	durationPolicy DurationPolicy,
) *float64 {
	var weightTotal, weightedSum float64
	for _, holding := range holdings {
		bond, ok := universeByISIN[holding.ISIN]
		if !ok {
			continue
		}
		duration := RateSensitiveDuration(bond, durationPolicy)
		if duration == nil {
			continue
		}
		if holding.MarketValueRub == nil || *holding.MarketValueRub <= 0 {
			continue
		}
		weight := *holding.MarketValueRub
		weightTotal += weight
		weightedSum += weight * *duration
	}
	if weightTotal <= 0 {
		return nil
	}
	v := weightedSum / weightTotal
	return &v
}
