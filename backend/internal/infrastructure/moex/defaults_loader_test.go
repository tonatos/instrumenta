package moex_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/moex"
)

func TestDefaultsLoaderApply(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "defaults.json")
	if err := os.WriteFile(path, []byte(`{
		"isin_flags": {
			"RU000ADEF1": {"has_default": true},
			"RU000ATECH1": {"has_technical_default": true}
		}
	}`), 0o644); err != nil {
		t.Fatal(err)
	}
	loader := moex.NewDefaultsLoaderWithPath(path)
	list := []bonds.BondRecord{
		{ISIN: "RU000ANORM1"},
		{ISIN: "RU000ADEF1"},
		{ISIN: "RU000ATECH1"},
	}
	out := loader.Apply(list)
	if out[0].HasDefault || out[0].HasTechnicalDefault {
		t.Fatal("normal bond should have no default flags")
	}
	if !out[1].HasDefault {
		t.Fatal("expected has_default")
	}
	if !out[2].HasTechnicalDefault {
		t.Fatal("expected has_technical_default")
	}
}
