package portfolio

import (
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

func TestExposureBySector_AggregatesAndSorts(t *testing.T) {
	today := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	b1 := bonds.BondRecord{
		ISIN: "ISIN1", Name: "B1", Sector: "financial",
		FaceValue: 1000, LotSize: 1, LastPrice: bonds.FloatPtr(100), AccruedInterest: bonds.FloatPtr(0),
		MaturityDate: bonds.TimePtr(today.AddDate(3, 0, 0)),
	}
	b2 := bonds.BondRecord{
		ISIN: "ISIN2", Name: "B2", Sector: "",
		FaceValue: 1000, LotSize: 1, LastPrice: bonds.FloatPtr(100), AccruedInterest: bonds.FloatPtr(0),
		MaturityDate: bonds.TimePtr(today.AddDate(3, 0, 0)),
	}

	byISIN := map[string]bonds.BondRecord{
		b1.ISIN: b1,
		b2.ISIN: b2,
	}
	lots := map[string]int{b1.ISIN: 3, b2.ISIN: 1}

	ex := ExposureBySector(byISIN, lots, 4_000)
	if len(ex) != 2 {
		t.Fatalf("expected 2 exposures, got %d", len(ex))
	}
	if ex[0].Key != "financial" {
		t.Fatalf("expected first sector financial, got %q", ex[0].Key)
	}
	if ex[1].Key != "unknown" {
		t.Fatalf("expected unknown sector bucket, got %q", ex[1].Key)
	}
	if ex[0].ValueRub != 3_000 {
		t.Fatalf("expected financial value 3000, got %.0f", ex[0].ValueRub)
	}
}

func TestAutoCompose_RespectsSectorCap(t *testing.T) {
	today := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	horizon := today.AddDate(3, 0, 0)

	mk := func(isin, sector string, score float64) bonds.BondRecord {
		return bonds.BondRecord{
			ISIN: isin, Name: isin, Sector: sector, IssuerName: "issuer_" + isin,
			FaceValue: 1000, LotSize: 1, LastPrice: bonds.FloatPtr(100), AccruedInterest: bonds.FloatPtr(0),
			MaturityDate: bonds.TimePtr(horizon),
			ProfileScores: map[string]float64{
				string(RiskProfileNormal): score,
			},
		}
	}

	universe := []bonds.BondRecord{
		mk("FIN1", "financial", 90),
		mk("FIN2", "financial", 80),
		mk("IT1", "it", 70),
		mk("UTIL1", "utilities", 60),
	}

	policy := DiversificationPolicy{MaxSectorShare: 0.35, MaxIssuerShare: 1.0}
	positions, _, _ := AutoCompose(
		100_000, universe, RiskProfileNormal, horizon, today, 14.5, 0.13, false, DefaultDurationPolicy,
		&policy, nil,
	)
	if len(positions) == 0 {
		t.Fatalf("expected positions, got none")
	}

	total := 0.0
	byISIN := make(map[string]bonds.BondRecord)
	lotsByISIN := make(map[string]int)
	for _, b := range universe {
		byISIN[b.ISIN] = b
	}
	for _, p := range positions {
		lotsByISIN[p.ISIN] = p.Lots
		if b, ok := byISIN[p.ISIN]; ok {
			if c := b.PricePerLotRub(); c != nil {
				total += *c * float64(p.Lots)
			}
		}
	}

	exposures := ExposureBySector(byISIN, lotsByISIN, 100_000)
	for _, e := range exposures {
		if e.Key == "financial" && e.Share > policy.MaxSectorShare+1e-9 {
			t.Fatalf("expected financial share <= %.2f, got %.4f", policy.MaxSectorShare, e.Share)
		}
	}
}

