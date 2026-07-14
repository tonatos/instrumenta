package market_signals

type SpreadAnomalyPolicy struct {
	MinPeers            int
	MaxRatingNotches    int
	MaxDurationDiffYears float64
	MinLiquidityRub     float64
	MinAnomalyPP        float64
	MinZScore           float64
}

var DefaultSpreadAnomalyPolicy = SpreadAnomalyPolicy{
	MinPeers:             5,
	MaxRatingNotches:     1,
	MaxDurationDiffYears: 1.0,
	MinLiquidityRub:      500_000,
	MinAnomalyPP:         8.0,
	MinZScore:            2.0,
}

type MarketRadarPolicy struct {
	Spread              SpreadAnomalyPolicy
	MaxAnomalies        int
	MaxDipIdeas         int
	DipSectorPanicPct   float64
	DipBondExcessPct    float64
}

var DefaultMarketRadarPolicy = MarketRadarPolicy{
	Spread:            DefaultSpreadAnomalyPolicy,
	MaxAnomalies:      50,
	MaxDipIdeas:       30,
	DipSectorPanicPct: -15,
	DipBondExcessPct:  5,
}

