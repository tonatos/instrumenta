package persistence

import (
	"context"
	"testing"
	"time"

	"github.com/jmoiron/sqlx"
)

func TestBondReferenceRepositoryManualOverrides(t *testing.T) {
	db := openTestDB(t)
	repo := NewBondReferenceRepository(db)

	ctx := context.Background()
	if _, err := repo.UpsertSmartLabRatings(ctx, map[string]string{
		"RU000A10CAQ0": "ruCC",
	}); err != nil {
		t.Fatal(err)
	}
	if err := repo.UpsertManualRating(ctx, "RU000A10CAQ0", "ruD"); err != nil {
		t.Fatal(err)
	}
	got, err := repo.ListRatingsByISINs(ctx, []string{"RU000A10CAQ0"})
	if err != nil {
		t.Fatal(err)
	}
	if got["RU000A10CAQ0"] != "ruD" {
		t.Fatalf("manual rating = %q, want ruD", got["RU000A10CAQ0"])
	}

	if _, err := repo.UpsertMOEXDefaultFlags(ctx, map[string]BondDefaultFlagRow{
		"RU000A10CAQ0": {ISIN: "RU000A10CAQ0", HasTechnicalDefault: true, Source: DefaultSourceMOEX},
	}); err != nil {
		t.Fatal(err)
	}
	if err := repo.UpsertManualDefault(ctx, "RU000A10CAQ0", false, false); err != nil {
		t.Fatal(err)
	}
	flags, err := repo.ListDefaultFlags(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if flags["RU000A10CAQ0"].HasTechnicalDefault {
		t.Fatal("expected manual default override to clear technical default")
	}
}

func openTestDB(t *testing.T) *sqlx.DB {
	t.Helper()
	db, err := sqlx.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	if err := ApplyMigrations(db, "sqlite", ""); err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`INSERT INTO issuer_rating_patterns (pattern, rating) VALUES ('сбер', 'ruAAA')`)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

func TestBondReferenceRepositorySettings(t *testing.T) {
	db := openTestDB(t)
	repo := NewBondReferenceRepository(db)
	ctx := context.Background()
	now := time.Now().UTC().Format(time.RFC3339)
	if err := repo.SetSetting(ctx, SettingBondRatingsScrapedAt, now); err != nil {
		t.Fatal(err)
	}
	at, err := repo.RatingsScrapedAt(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if at.IsZero() {
		t.Fatal("expected parsed scraped_at")
	}
}
