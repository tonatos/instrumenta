package market_signals

import "github.com/tonatos/instrumenta/backend/internal/domain/bonds"

func FilterRadarUniverse(list []bonds.BondRecord, policy SpreadAnomalyPolicy) []bonds.BondRecord {
	minLiq := policy.MinLiquidityRub
	if minLiq <= 0 {
		minLiq = DefaultSpreadAnomalyPolicy.MinLiquidityRub
	}
	var out []bonds.BondRecord
	for _, b := range list {
		if b.HasDefault || b.HasTechnicalDefault || b.SubordinatedFlag {
			continue
		}
		if b.Sector == "" || b.YTMNet == nil {
			continue
		}
		if b.FilterVolumeRub() < minLiq {
			continue
		}
		out = append(out, b)
	}
	return out
}
