package market_signals_test

import (
	"context"
	"testing"
	"time"

	appmarketsignals "github.com/tonatos/bond-monitor/backend/internal/application/market_signals"
	appportfolio "github.com/tonatos/bond-monitor/backend/internal/application/portfolio"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/market_signals"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

func TestGetRadarUseCaseOverlaysPortfolios(t *testing.T) {
	ctx := context.Background()
	db, err := persistence.Open("file:memdb1?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatal(err)
	}

	radarRepo := persistence.NewMarketRadarRepository(db.DB)
	payload, err := appmarketsignals.StoredRadarPayloadForTest(domain.RadarSnapshot{
		Anomalies: []domain.AnomalyCandidate{
			{ISIN: "RU000A1", Secid: "A1", Name: "Bond A", Sector: "energy"},
		},
		Sectors: []domain.SectorHeatmapRow{{Sector: "energy", Change7dPct: -16}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := radarRepo.SaveRun(ctx, persistence.MarketRadarRun{
		ID: "r1", ScannedAt: time.Now().UTC().Format(time.RFC3339), UniverseCount: 1, PayloadJSON: payload,
	}); err != nil {
		t.Fatal(err)
	}

	portfolioRepo := persistence.NewPortfolioRepository(db)
	portfolioSvc := appportfolio.NewService(portfolioRepo, nil)
	horizon := time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC)
	_, err = portfolioRepo.Save(ctx, portfolio.Portfolio{
		ID: "p1", Name: "Test", CreatedAt: time.Now().UTC().Format(time.RFC3339),
		UpdatedAt: time.Now().UTC().Format(time.RFC3339), InitialAmountRub: 100_000,
		HorizonDate: horizon, RiskProfile: portfolio.RiskProfileNormal,
		CashBalanceRub: 100_000, Mode: portfolio.PortfolioModeSimulation,
		RiskBaselines: map[string]portfolio.RiskSnapshot{},
		Positions: []portfolio.PortfolioPosition{{ISIN: "RU000A1", Name: "Bond A"}},
	})
	if err != nil {
		t.Fatal(err)
	}

	uc := appmarketsignals.NewGetRadarUseCase(radarRepo, portfolioSvc)
	resp, err := uc.Get(ctx, true)
	if err != nil {
		t.Fatal(err)
	}
	if len(resp.Anomalies) != 1 || len(resp.Anomalies[0].InPortfolios) != 1 || resp.Anomalies[0].InPortfolios[0] != "p1" {
		t.Fatalf("unexpected overlay: %+v", resp.Anomalies)
	}
}
