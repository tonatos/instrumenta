package market_signals

import (
	"sort"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

func bondChangePct(now, past *float64) (float64, bool) {
	if now == nil || past == nil || *past <= 0 {
		return 0, false
	}
	return (*now - *past) / (*past) * 100, true
}

func peerPriceChanges(
	bond bonds.BondRecord,
	universe []bonds.BondRecord,
	todayByISIN, pastByISIN map[string]BondSnapshot,
	policy SpreadAnomalyPolicy,
) []float64 {
	var changes []float64
	for _, peer := range PeerGroup(bond, universe, policy) {
		cur, okNow := todayByISIN[peer.ISIN]
		prev, okPast := pastByISIN[peer.ISIN]
		if !okNow || !okPast {
			continue
		}
		if ch, ok := bondChangePct(cur.LastPricePct, prev.LastPricePct); ok {
			changes = append(changes, ch)
		}
	}
	return changes
}

func medianFloat(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	cp := append([]float64(nil), values...)
	sort.Float64s(cp)
	if len(cp)%2 == 1 {
		return cp[len(cp)/2]
	}
	return (cp[len(cp)/2-1] + cp[len(cp)/2]) / 2
}

func RankDipIdeas(
	universe []bonds.BondRecord,
	todayByISIN, pastByISIN map[string]BondSnapshot,
	scoresByISIN map[string]float64,
	policy MarketRadarPolicy,
	maxResults int,
) []DipIdea {
	if maxResults <= 0 {
		maxResults = 30
	}
	spreadPolicy := policy.Spread
	if spreadPolicy.MinPeers == 0 {
		spreadPolicy = DefaultSpreadAnomalyPolicy
	}

	var marketChanges []float64
	for isin, cur := range todayByISIN {
		prev, ok := pastByISIN[isin]
		if !ok {
			continue
		}
		if ch, ok := bondChangePct(cur.LastPricePct, prev.LastPricePct); ok {
			marketChanges = append(marketChanges, ch)
		}
	}
	marketMedian := medianFloat(marketChanges)

	var ideas []DipIdea
	for _, bond := range universe {
		if bond.HasDefault || bond.HasTechnicalDefault {
			continue
		}
		cur, okNow := todayByISIN[bond.ISIN]
		prev, okPast := pastByISIN[bond.ISIN]
		if !okNow || !okPast {
			continue
		}
		bondCh, okBond := bondChangePct(cur.LastPricePct, prev.LastPricePct)
		if !okBond {
			continue
		}
		sectorMedian := medianFloat(peerPriceChanges(bond, universe, todayByISIN, pastByISIN, spreadPolicy))
		attr := BuildAttribution(bondCh, sectorMedian, marketMedian)

		if attr.SectorChange7dPct >= policy.DipSectorPanicPct {
			continue
		}
		if attr.BondChange7dPct >= attr.SectorChange7dPct-policy.DipBondExcessPct {
			continue
		}
		if attr.Interpretation == "idiosyncratic_drop" {
			continue
		}

		score := scoresByISIN[bond.ISIN]
		ideas = append(ideas, DipIdea{
			ISIN:                     bond.ISIN,
			Secid:                    bond.Secid,
			Name:                     bond.Name,
			Sector:                   bond.Sector,
			BondChange7dPct:          attr.BondChange7dPct,
			SectorChange7dPct:        attr.SectorChange7dPct,
			IdiosyncraticExcess7dPct: attr.IdiosyncraticExcess7dPct,
			Score:                    score,
			Interpretation:           attr.Interpretation,
		})
	}

	sort.Slice(ideas, func(i, j int) bool {
		if ideas[i].IdiosyncraticExcess7dPct != ideas[j].IdiosyncraticExcess7dPct {
			return ideas[i].IdiosyncraticExcess7dPct < ideas[j].IdiosyncraticExcess7dPct
		}
		return ideas[i].Score > ideas[j].Score
	})
	if len(ideas) > maxResults {
		ideas = ideas[:maxResults]
	}
	return ideas
}

func BuildSectorHeatmap(
	universe []bonds.BondRecord,
	todayByISIN, pastByISIN map[string]BondSnapshot,
	anomalies []AnomalyCandidate,
	dipIdeas []DipIdea,
	policy SpreadAnomalyPolicy,
) []SectorHeatmapRow {
	type acc struct {
		changes []float64
		bonds   int
	}
	bySector := map[string]*acc{}
	for _, bond := range universe {
		cur, okNow := todayByISIN[bond.ISIN]
		prev, okPast := pastByISIN[bond.ISIN]
		if !okNow || !okPast || bond.Sector == "" {
			continue
		}
		ch, ok := bondChangePct(cur.LastPricePct, prev.LastPricePct)
		if !ok {
			continue
		}
		a := bySector[bond.Sector]
		if a == nil {
			a = &acc{}
			bySector[bond.Sector] = a
		}
		a.changes = append(a.changes, ch)
		a.bonds++
	}

	anomalyBySector := map[string]int{}
	for _, a := range anomalies {
		anomalyBySector[a.Sector]++
	}
	dipBySector := map[string]int{}
	for _, d := range dipIdeas {
		dipBySector[d.Sector]++
	}

	rows := make([]SectorHeatmapRow, 0, len(bySector))
	for sector, a := range bySector {
		rows = append(rows, SectorHeatmapRow{
			Sector:       sector,
			Change7dPct:  medianFloat(a.changes),
			AnomalyCount: anomalyBySector[sector],
			DipIdeaCount: dipBySector[sector],
			BondCount:    a.bonds,
		})
	}
	sort.Slice(rows, func(i, j int) bool {
		return rows[i].Change7dPct < rows[j].Change7dPct
	})
	return rows
}
