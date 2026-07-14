package market_signals

func ScanMarketRadar(params ScanParams) RadarSnapshot {
	policy := params.Policy
	if policy.Spread.MinPeers == 0 {
		policy = DefaultMarketRadarPolicy
	}
	universe := FilterRadarUniverse(params.Universe, policy.Spread)
	anomalies := RankSpreadAnomalies(
		universe,
		params.KeyRatePP,
		params.TaxRateFraction,
		policy.Spread,
		policy.MaxAnomalies,
	)
	dipIdeas := RankDipIdeas(
		universe,
		params.TodayByISIN,
		params.PastByISIN,
		params.ScoresByISIN,
		policy,
		policy.MaxDipIdeas,
	)
	sectors := BuildSectorHeatmap(
		universe,
		params.TodayByISIN,
		params.PastByISIN,
		anomalies,
		dipIdeas,
		policy.Spread,
	)
	scannedAt := params.ScannedAt
	return RadarSnapshot{
		ScannedAt:       scannedAt,
		UniverseScanned: len(universe),
		Sectors:         sectors,
		Anomalies:       anomalies,
		DipIdeas:        dipIdeas,
	}
}
