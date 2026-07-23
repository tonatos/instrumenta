package moex

import (
	"context"
	"testing"

	"github.com/jmoiron/sqlx"
	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

func TestDefaultFlagsServiceApply(t *testing.T) {
	db, err := sqlx.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := persistence.ApplyMigrations(db, "sqlite", ""); err != nil {
		t.Fatal(err)
	}
	repo := persistence.NewBondReferenceRepository(db)
	ctx := context.Background()
	if _, err := repo.UpsertMOEXDefaultFlags(ctx, map[string]persistence.BondDefaultFlagRow{
		"RU000ATECH1": {
			ISIN:                "RU000ATECH1",
			HasTechnicalDefault: true,
			Source:              persistence.DefaultSourceMOEX,
		},
	}); err != nil {
		t.Fatal(err)
	}
	svc := NewDefaultFlagsService(repo)
	bs := []bonds.BondRecord{{ISIN: "RU000ATECH1", Secid: "TECH1"}}
	out := svc.Apply(ctx, bs)
	if !out[0].HasTechnicalDefault {
		t.Fatal("expected technical default")
	}
}
