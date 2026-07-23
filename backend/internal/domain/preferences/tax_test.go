package preferences_test

import (
	"testing"

	"github.com/tonatos/bond-monitor/backend/internal/domain/preferences"
)

func TestNormalizeTaxRatePct(t *testing.T) {
	for _, pct := range []float64{0, 13, 15, 18, 20, 22} {
		got, err := preferences.NormalizeTaxRatePct(pct)
		if err != nil || got != pct {
			t.Fatalf("pct=%v: got %v err=%v", pct, got, err)
		}
	}
	if _, err := preferences.NormalizeTaxRatePct(14); err == nil {
		t.Fatal("expected error for 14")
	}
	if _, err := preferences.NormalizeTaxRatePct(13.5); err == nil {
		t.Fatal("expected error for 13.5")
	}
}

func TestTaxRateFraction(t *testing.T) {
	if got := preferences.TaxRateFraction(13); got != 0.13 {
		t.Fatalf("got %v", got)
	}
	if got := preferences.TaxRateFraction(0); got != 0 {
		t.Fatalf("got %v", got)
	}
}
