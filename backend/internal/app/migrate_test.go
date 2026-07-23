package app

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

func TestRunMigrationsAppliesAllSQLFiles(t *testing.T) {
	root := repoRootForTest(t)
	t.Setenv("BOND_MONITOR_REPO_ROOT", root)

	db, err := persistence.Open("file:memdb_migrate?mode=memory&cache=shared")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	if err := runMigrations(context.Background(), db); err != nil {
		t.Fatal(err)
	}

	for _, table := range []string{"portfolios", "spread_snapshots", "market_radar_runs", "bond_credit_ratings", "bond_default_flags", "issuer_rating_patterns"} {
		var name string
		err := db.QueryRowContext(context.Background(),
			"SELECT name FROM sqlite_master WHERE type='table' AND name=?",
			table,
		).Scan(&name)
		if err != nil {
			t.Fatalf("table %s: %v", table, err)
		}
	}
}

func repoRootForTest(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	dir := wd
	for {
		if _, err := os.Stat(filepath.Join(dir, "backend", "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("repo root not found")
		}
		dir = parent
	}
}
