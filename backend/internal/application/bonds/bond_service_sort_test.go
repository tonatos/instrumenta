package bonds_test

import (
	"testing"

	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	infraBonds "github.com/tonatos/bond-monitor/backend/internal/infrastructure/bonds"
)

func TestListBondsScoreSortDescPutsHighestFirst(t *testing.T) {
	t.Cleanup(appbonds.InvalidateAllBondCaches)

	svc := appbonds.NewServiceWithDeps(16, 0.13, "", nil, nil, nil, nil)
	key := infraBonds.CacheKey{KeyRate: 16, TaxRate: 0.13, TokenFingerprint: infraBonds.TokenFingerprint("")}
	infraBonds.Put(key, []bonds.BondRecord{
		scoredBond("LOW", 40),
		scoredBond("HIGH", 90),
		scoredBond("MID", 70),
	}, "test")

	result := svc.ListBonds(
		bonds.BondListQuery{SortBy: "score", SortDesc: true, Page: 1, PageSize: 10},
		portfolio.DefaultDurationPolicy,
		portfolio.RiskProfileNormal,
		16, 0.13,
	)
	if len(result.Bonds) != 3 {
		t.Fatalf("expected 3 bonds, got %d", len(result.Bonds))
	}
	if result.Bonds[0].Secid != "HIGH" {
		t.Fatalf("sort_desc=true should put highest score first, got %s", result.Bonds[0].Secid)
	}
	if result.Bonds[2].Secid != "LOW" {
		t.Fatalf("sort_desc=true should put lowest score last, got %s", result.Bonds[2].Secid)
	}
}

func TestListBondsScoreSortAscPutsLowestFirst(t *testing.T) {
	t.Cleanup(appbonds.InvalidateAllBondCaches)

	svc := appbonds.NewServiceWithDeps(16, 0.13, "", nil, nil, nil, nil)
	key := infraBonds.CacheKey{KeyRate: 16, TaxRate: 0.13, TokenFingerprint: infraBonds.TokenFingerprint("")}
	infraBonds.Put(key, []bonds.BondRecord{
		scoredBond("LOW", 40),
		scoredBond("HIGH", 90),
		scoredBond("MID", 70),
	}, "test")

	result := svc.ListBonds(
		bonds.BondListQuery{SortBy: "score", SortDesc: false, Page: 1, PageSize: 10},
		portfolio.DefaultDurationPolicy,
		portfolio.RiskProfileNormal,
		16, 0.13,
	)
	if result.Bonds[0].Secid != "LOW" {
		t.Fatalf("sort_desc=false should put lowest score first, got %s", result.Bonds[0].Secid)
	}
}

func scoredBond(secid string, score float64) bonds.BondRecord {
	s := score
	return bonds.BondRecord{
		Secid: secid,
		ISIN:  "RU" + secid,
		Name:  secid,
		Score: &s,
		ProfileScores: map[string]float64{
			"conservative": score,
			"normal":       score,
			"aggressive":   score,
		},
	}
}
