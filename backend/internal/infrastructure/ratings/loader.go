package ratings

import (
	"context"
	"log"
	"strings"
	"sync"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

// Loader applies credit ratings from SQLite reference tables.
type Loader struct {
	repo BondReferenceStore

	mu             sync.Mutex
	cachedPatterns map[string]string
}

// NewLoader creates a ratings loader backed by SQLite.
func NewLoader(repo BondReferenceStore) *Loader {
	return &Loader{repo: repo}
}

func (l *Loader) ApplyRatings(ctx context.Context, bs []bonds.BondRecord) []bonds.BondRecord {
	if l.repo == nil || len(bs) == 0 {
		return bs
	}
	isins := make([]string, 0, len(bs))
	for _, b := range bs {
		if b.ISIN != "" {
			isins = append(isins, b.ISIN)
		}
	}
	byISIN, err := l.repo.ListRatingsByISINs(ctx, isins)
	if err != nil {
		log.Printf("ratings: list by isin: %v", err)
		byISIN = map[string]string{}
	}
	patterns, err := l.loadPatterns(ctx)
	if err != nil {
		log.Printf("ratings: list issuer patterns: %v", err)
		patterns = map[string]string{}
	}
	for i := range bs {
		if rating, ok := byISIN[bs[i].ISIN]; ok {
			r := rating
			bs[i].CreditRating = &r
			continue
		}
		nameLower := strings.ToLower(bs[i].Name)
		for pattern, rating := range patterns {
			if strings.Contains(nameLower, pattern) {
				r := rating
				bs[i].CreditRating = &r
				break
			}
		}
	}
	return bs
}

func (l *Loader) RefreshFromSmartLab(ctx context.Context) (int, error) {
	return RefreshFromSmartLab(ctx, l.repo, nil)
}

func (l *Loader) MaybeRefreshStale(ctx context.Context) {
	if !NeedsRatingsRefresh(ctx, l.repo) {
		return
	}
	go func() {
		if _, err := l.RefreshFromSmartLab(context.Background()); err != nil {
			log.Printf("ratings: background refresh failed: %v", err)
		}
	}()
}

func (l *Loader) loadPatterns(ctx context.Context) (map[string]string, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.cachedPatterns != nil {
		return l.cachedPatterns, nil
	}
	patterns, err := l.repo.ListIssuerPatterns(ctx)
	if err != nil {
		return nil, err
	}
	l.cachedPatterns = patterns
	return patterns, nil
}

func (l *Loader) InvalidatePatternCache() {
	l.mu.Lock()
	l.cachedPatterns = nil
	l.mu.Unlock()
}

var _ bonds.RatingsLoader = (*Loader)(nil)
