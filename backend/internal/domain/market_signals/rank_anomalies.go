package market_signals

import (
	"sort"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

func RankSpreadAnomalies(
	universe []bonds.BondRecord,
	keyRatePP, taxRateFraction float64,
	policy SpreadAnomalyPolicy,
	maxResults int,
) []AnomalyCandidate {
	if maxResults <= 0 {
		maxResults = 50
	}
	var candidates []AnomalyCandidate
	for _, bond := range universe {
		targetSpread := CreditSpreadPP(bond, keyRatePP, taxRateFraction)
		if targetSpread == nil {
			continue
		}
		peers := PeerGroup(bond, universe, policy)
		if len(peers) < policy.MinPeers {
			continue
		}
		spreads := make([]float64, 0, len(peers))
		for _, p := range peers {
			if s := CreditSpreadPP(p, keyRatePP, taxRateFraction); s != nil {
				spreads = append(spreads, *s)
			}
		}
		stats := SpreadStatsFromPeers(spreads)
		if stats == nil || stats.Peers < policy.MinPeers {
			continue
		}
		delta := *targetSpread - stats.ExpectedPP
		z := ZScore(*targetSpread, stats.ExpectedPP, stats.StdDevPP)
		isAnomaly := delta >= policy.MinAnomalyPP
		if z != nil && *z >= policy.MinZScore {
			isAnomaly = true
		}
		if !isAnomaly {
			continue
		}
		candidates = append(candidates, AnomalyCandidate{
			ISIN:             bond.ISIN,
			Secid:            bond.Secid,
			Name:             bond.Name,
			Sector:           bond.Sector,
			SpreadPP:         *targetSpread,
			ExpectedSpreadPP: stats.ExpectedPP,
			DeltaPP:          delta,
			ZScore:           z,
			Peers:            stats.Peers,
		})
	}
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].DeltaPP != candidates[j].DeltaPP {
			return candidates[i].DeltaPP > candidates[j].DeltaPP
		}
		zi, zj := 0.0, 0.0
		if candidates[i].ZScore != nil {
			zi = *candidates[i].ZScore
		}
		if candidates[j].ZScore != nil {
			zj = *candidates[j].ZScore
		}
		return zi > zj
	})
	if len(candidates) > maxResults {
		candidates = candidates[:maxResults]
	}
	return candidates
}
