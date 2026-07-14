package ratings

import (
	"context"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

type stubBondRefRepo struct {
	ratings  map[string]string
	patterns map[string]string
}

func (s *stubBondRefRepo) UpsertSmartLabRatings(context.Context, map[string]string) (int, error) {
	return 0, nil
}
func (s *stubBondRefRepo) ListRatingsByISINs(_ context.Context, isins []string) (map[string]string, error) {
	out := make(map[string]string, len(isins))
	for _, isin := range isins {
		if v, ok := s.ratings[isin]; ok {
			out[isin] = v
		}
	}
	return out, nil
}
func (s *stubBondRefRepo) ListIssuerPatterns(context.Context) (map[string]string, error) {
	return s.patterns, nil
}
func (s *stubBondRefRepo) RatingsScrapedAt(context.Context) (time.Time, error) {
	return time.Time{}, nil
}

func TestApplyRatingsISINOverridesPattern(t *testing.T) {
	repo := &stubBondRefRepo{
		ratings: map[string]string{"RU000A10CAQ0": "ruCC"},
		patterns: map[string]string{
			"альфа": "ruAA+",
		},
	}
	loader := NewLoader(repo)
	bs := []bonds.BondRecord{{
		ISIN: "RU000A10CAQ0",
		Name: "АЛЬФАДОНБ1",
	}}
	out := loader.ApplyRatings(context.Background(), bs)
	if out[0].CreditRating == nil || *out[0].CreditRating != "ruCC" {
		got := "<nil>"
		if out[0].CreditRating != nil {
			got = *out[0].CreditRating
		}
		t.Fatalf("credit rating = %s, want ruCC", got)
	}
}

func TestApplyRatingsPatternFallback(t *testing.T) {
	repo := &stubBondRefRepo{
		patterns: map[string]string{"сбер": "ruAAA"},
	}
	loader := NewLoader(repo)
	bs := []bonds.BondRecord{{ISIN: "RU000ATEST1", Name: "СберБ001"}}
	out := loader.ApplyRatings(context.Background(), bs)
	if out[0].CreditRating == nil || *out[0].CreditRating != "ruAAA" {
		t.Fatalf("expected ruAAA fallback, got %#v", out[0].CreditRating)
	}
}
