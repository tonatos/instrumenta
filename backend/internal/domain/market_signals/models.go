package market_signals

import (
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

type BondSnapshot struct {
	CreditSpreadPP float64
	LastPricePct   *float64
	Sector         string
}

type SectorHeatmapRow struct {
	Sector         string
	Change7dPct    float64
	AnomalyCount   int
	DipIdeaCount   int
	BondCount      int
}

type AnomalyCandidate struct {
	ISIN             string
	Secid            string
	Name             string
	Sector           string
	SpreadPP         float64
	ExpectedSpreadPP float64
	DeltaPP          float64
	ZScore           *float64
	Peers            int
}

type DipIdea struct {
	ISIN                     string
	Secid                    string
	Name                     string
	Sector                   string
	BondChange7dPct          float64
	SectorChange7dPct        float64
	IdiosyncraticExcess7dPct float64
	Score                    float64
	Interpretation           string
}

type RadarSnapshot struct {
	ScannedAt        time.Time
	UniverseScanned  int
	Sectors          []SectorHeatmapRow
	Anomalies        []AnomalyCandidate
	DipIdeas         []DipIdea
}

type ScanParams struct {
	Universe        []bonds.BondRecord
	TodayByISIN     map[string]BondSnapshot
	PastByISIN      map[string]BondSnapshot
	KeyRatePP       float64
	TaxRateFraction float64
	Policy          MarketRadarPolicy
	ScoresByISIN    map[string]float64
	ScannedAt       time.Time
}
