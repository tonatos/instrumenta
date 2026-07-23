package market_signals_test

import (
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/market_signals"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading/testutil"
)

func TestScanMarketRadarFindsAnomalyAndDipIdea(t *testing.T) {
	rating := "ruA"
	sector := "energy"
	liq := 1_000_000.0
	dur := 365.0

	target := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Secid, b.Name = "RU000DIP1", "DIP1", "Dip Target"
		b.CreditRating = &rating
		b.Sector = sector
		b.PrevVolumeRub = &liq
		b.DurationDays = &dur
		ytmNet := 26.0
		b.YTMNet = &ytmNet
		last := 88.0
		b.LastPrice = &last
	})

	var peers []bonds.BondRecord
	for i := 0; i < 6; i++ {
		peers = append(peers, testutil.MakeBond(func(b *bonds.BondRecord) {
			b.ISIN, b.Secid, b.Name = "RU000PEER"+string(rune('A'+i)), "P"+string(rune('A'+i)), "Peer"
			b.CreditRating = &rating
			b.Sector = sector
			b.PrevVolumeRub = &liq
			b.DurationDays = &dur
			ytmNet := 14.0
			b.YTMNet = &ytmNet
			last := 100.0
			b.LastPrice = &last
		}))
	}

	universe := append([]bonds.BondRecord{target}, peers...)
	today := map[string]market_signals.BondSnapshot{}
	past := map[string]market_signals.BondSnapshot{}
	for _, b := range universe {
		curPrice := 100.0
		prevPrice := 100.0
		if b.ISIN == target.ISIN {
			curPrice = 88.0
			prevPrice = 100.0
		}
		today[b.ISIN] = market_signals.BondSnapshot{
			CreditSpreadPP: 20,
			LastPricePct:   &curPrice,
			Sector:         sector,
		}
		if b.ISIN == target.ISIN {
			prevPrice = 100.0
		}
		p := prevPrice
		past[b.ISIN] = market_signals.BondSnapshot{
			CreditSpreadPP: 10,
			LastPricePct:   &p,
			Sector:         sector,
		}
	}

	// Peer sector drop ~ -12%, target -12% vs sector median triggers dip when sector panic tuned
	for i, b := range peers {
		cur := 88.0
		prev := 100.0
		today[b.ISIN] = market_signals.BondSnapshot{CreditSpreadPP: 8, LastPricePct: &cur, Sector: sector}
		past[b.ISIN] = market_signals.BondSnapshot{CreditSpreadPP: 6, LastPricePct: &prev, Sector: sector}
		_ = i
	}

	snap := market_signals.ScanMarketRadar(market_signals.ScanParams{
		Universe:        universe,
		TodayByISIN:     today,
		PastByISIN:      past,
		KeyRatePP:       10,
		TaxRateFraction: 0,
		Policy:          market_signals.DefaultMarketRadarPolicy,
		ScoresByISIN:    map[string]float64{target.ISIN: 72},
		ScannedAt:       time.Date(2026, 7, 14, 18, 0, 0, 0, time.UTC),
	})

	if len(snap.Anomalies) == 0 {
		t.Fatal("expected spread anomaly")
	}
	if snap.Anomalies[0].ISIN != target.ISIN {
		t.Fatalf("expected target anomaly, got %s", snap.Anomalies[0].ISIN)
	}
	if len(snap.Sectors) == 0 {
		t.Fatal("expected sector heatmap row")
	}
	if snap.UniverseScanned != len(universe) {
		t.Fatalf("universe scanned %d want %d", snap.UniverseScanned, len(universe))
	}
}

func TestFilterRadarUniverseSkipsDefault(t *testing.T) {
	b := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.HasDefault = true
		b.Sector = "energy"
		ytm := 12.0
		b.YTMNet = &ytm
		liq := 1_000_000.0
		b.PrevVolumeRub = &liq
	})
	out := market_signals.FilterRadarUniverse([]bonds.BondRecord{b}, market_signals.DefaultSpreadAnomalyPolicy)
	if len(out) != 0 {
		t.Fatalf("expected empty, got %d", len(out))
	}
}
