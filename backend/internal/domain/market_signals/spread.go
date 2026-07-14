package market_signals

import (
	"math"
	"sort"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

func RiskFreeNetPP(keyRatePP, taxRateFraction float64) float64 {
	return keyRatePP * (1 - taxRateFraction)
}

// CreditSpreadPP returns excess yield above risk-free (after tax) in percentage points.
func CreditSpreadPP(b bonds.BondRecord, keyRatePP, taxRateFraction float64) *float64 {
	if b.YTMNet == nil {
		return nil
	}
	rf := RiskFreeNetPP(keyRatePP, taxRateFraction)
	v := *b.YTMNet - rf
	return &v
}

type SpreadStats struct {
	ExpectedPP float64
	StdDevPP   float64
	Peers      int
}

func SpreadStatsFromPeers(spreads []float64) *SpreadStats {
	if len(spreads) == 0 {
		return nil
	}
	sort.Float64s(spreads)
	median := spreads[len(spreads)/2]
	if len(spreads)%2 == 0 {
		median = (spreads[len(spreads)/2-1] + spreads[len(spreads)/2]) / 2
	}
	mean := 0.0
	for _, v := range spreads {
		mean += v
	}
	mean /= float64(len(spreads))
	variance := 0.0
	for _, v := range spreads {
		d := v - mean
		variance += d * d
	}
	variance /= float64(len(spreads))
	stddev := math.Sqrt(variance)
	return &SpreadStats{ExpectedPP: median, StdDevPP: stddev, Peers: len(spreads)}
}

func ZScore(value, mean, stddev float64) *float64 {
	if stddev <= 0 {
		return nil
	}
	v := (value - mean) / stddev
	return &v
}

