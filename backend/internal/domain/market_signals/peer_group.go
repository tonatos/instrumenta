package market_signals

import "github.com/tonatos/instrumenta/backend/internal/domain/bonds"

func ratingOrdinal(b bonds.BondRecord) *int {
	if b.CreditRating == nil {
		return nil
	}
	if ord, ok := bonds.RatingOrder[*b.CreditRating]; ok {
		return &ord
	}
	return nil
}

func withinIntDiff(a, b *int, maxDiff int) bool {
	if a == nil || b == nil {
		return false
	}
	d := *a - *b
	if d < 0 {
		d = -d
	}
	return d <= maxDiff
}

func durationYears(b bonds.BondRecord) *float64 {
	return b.DurationYears()
}

func withinFloatDiff(a, b *float64, maxDiff float64) bool {
	if a == nil || b == nil {
		return false
	}
	d := *a - *b
	if d < 0 {
		d = -d
	}
	return d <= maxDiff
}

// PeerGroup returns bonds similar to target for relative spread comparisons.
// It is intentionally simple and stable: sector + rating window + duration window + liquidity floor.
func PeerGroup(target bonds.BondRecord, universe []bonds.BondRecord, policy SpreadAnomalyPolicy) []bonds.BondRecord {
	if target.Sector == "" || target.YTMNet == nil {
		return nil
	}
	targetRating := ratingOrdinal(target)
	targetDur := durationYears(target)
	var peers []bonds.BondRecord
	for _, b := range universe {
		if b.ISIN == target.ISIN {
			continue
		}
		if b.Sector == "" || b.Sector != target.Sector {
			continue
		}
		if b.FilterVolumeRub() < policy.MinLiquidityRub {
			continue
		}
		if b.YTMNet == nil {
			continue
		}
		if policy.MaxRatingNotches > 0 {
			if !withinIntDiff(targetRating, ratingOrdinal(b), policy.MaxRatingNotches) {
				continue
			}
		}
		if policy.MaxDurationDiffYears > 0 {
			if !withinFloatDiff(targetDur, durationYears(b), policy.MaxDurationDiffYears) {
				continue
			}
		}
		peers = append(peers, b)
	}
	return peers
}

