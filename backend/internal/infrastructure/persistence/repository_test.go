package persistence_test

import (
	"context"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

func openTestDB(t *testing.T) *persistence.DB {
	t.Helper()
	db, err := persistence.Open("file::memory:?cache=shared")
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	return db
}

func TestPortfolioRepositoryCRUD(t *testing.T) {
	db := openTestDB(t)
	defer db.Close()
	repo := persistence.NewPortfolioRepository(db)
	ctx := context.Background()

	horizon := time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC)
	created, err := repo.Save(ctx, portfolio.Portfolio{
		ID: "p1", Name: "Test", CreatedAt: time.Now().UTC().Format(time.RFC3339),
		UpdatedAt: time.Now().UTC().Format(time.RFC3339), InitialAmountRub: 100_000,
		HorizonDate: horizon, RiskProfile: portfolio.RiskProfileNormal,
		CashBalanceRub: 100_000, Mode: portfolio.PortfolioModeSimulation,
		RiskBaselines: map[string]portfolio.RiskSnapshot{},
		Positions: []portfolio.PortfolioPosition{{
			ISIN: "RU000A0JX0J2", Secid: "TEST", Name: "ОФЗ", Lots: 10, LotSize: 1,
			PurchaseCleanPricePct: 100, PurchaseDirtyPriceRub: 1000, PurchaseDate: time.Now(),
			PurchaseAmountRub: 10_000, FaceValue: 1000,
		}},
	})
	if err != nil {
		t.Fatalf("save: %v", err)
	}
	if created.ID != "p1" {
		t.Fatalf("expected p1, got %s", created.ID)
	}

	got, err := repo.GetByID(ctx, "p1")
	if err != nil || got == nil {
		t.Fatalf("get: %v", err)
	}
	if len(got.Positions) != 1 || got.Positions[0].ISIN != "RU000A0JX0J2" {
		t.Fatalf("positions not persisted: %+v", got.Positions)
	}

	all, err := repo.ListAll(ctx)
	if err != nil || len(all) != 1 {
		t.Fatalf("list: %v len=%d", err, len(all))
	}

	ok, err := repo.Delete(ctx, "p1")
	if err != nil || !ok {
		t.Fatalf("delete: %v ok=%v", err, ok)
	}
	missing, err := repo.GetByID(ctx, "p1")
	if err != nil || missing != nil {
		t.Fatalf("expected nil after delete, got %v err=%v", missing, err)
	}
}

func TestFavoritesRepository(t *testing.T) {
	db := openTestDB(t)
	defer db.Close()
	repo := persistence.NewFavoritesRepository(db)
	ctx := context.Background()

	if err := repo.Add(ctx, "RU000A0JX0J2"); err != nil {
		t.Fatalf("add: %v", err)
	}
	isins, err := repo.ListISINs(ctx)
	if err != nil || len(isins) != 1 {
		t.Fatalf("list: %v %+v", err, isins)
	}
	removed, err := repo.SyncVisible(ctx, map[string]struct{}{})
	if err != nil || len(removed) != 1 {
		t.Fatalf("sync visible: %v %+v", err, removed)
	}
}

func TestDeploySessionRepository(t *testing.T) {
	db := openTestDB(t)
	defer db.Close()
	repo := persistence.NewDeploySessionRepository(db)
	ctx := context.Background()
	now := time.Now().UTC()
	expires := now.Add(24 * time.Hour)

	session := trading.DeploySession{
		ID: "s1", PortfolioID: "p1", Status: trading.DeploySessionActive,
		CashSnapshotRub: 50_000, CreatedAt: now, ExpiresAt: expires,
		Items: []trading.DeploySessionItem{{
			ID: "i1", Kind: trading.DeploySessionItemBuy, ISIN: "RU000A0JX0J2", Name: "ОФЗ",
			Lots: 1, SuggestedPricePct: 100, EstimatedAmountRub: 1000, Status: trading.ItemStatusPending,
			Urgency: trading.SuggestionUrgencyNormal,
		}},
	}
	saved, err := repo.Save(ctx, session)
	if err != nil {
		t.Fatalf("save: %v", err)
	}
	if len(saved.Items) != 1 {
		t.Fatalf("items lost: %+v", saved.Items)
	}
	active, err := repo.GetActive(ctx, "p1")
	if err != nil || active == nil || active.ID != "s1" {
		t.Fatalf("get active: %v %+v", err, active)
	}
	has, err := repo.HasActive(ctx, "p1")
	if err != nil || !has {
		t.Fatalf("has active: %v %v", err, has)
	}
}
