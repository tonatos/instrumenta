package ratings

import (
	"context"
	"time"
)

const ratingsStaleAfter = 7 * 24 * time.Hour

// BondReferenceStore persists scraped ratings and issuer patterns.
type BondReferenceStore interface {
	UpsertSmartLabRatings(ctx context.Context, ratings map[string]string) (int, error)
	ListRatingsByISINs(ctx context.Context, isins []string) (map[string]string, error)
	ListIssuerPatterns(ctx context.Context) (map[string]string, error)
	RatingsScrapedAt(ctx context.Context) (time.Time, error)
}

// RefreshFromSmartLab scrapes smart-lab and upserts ratings into SQLite.
func RefreshFromSmartLab(ctx context.Context, repo BondReferenceStore, fetch pageFetcher) (int, error) {
	if fetch == nil {
		fetch = defaultHTTPFetcher
	}
	ratings, err := ScrapeSmartLabRatings(fetch)
	if err != nil {
		return 0, err
	}
	return repo.UpsertSmartLabRatings(ctx, ratings)
}

// NeedsRatingsRefresh reports whether smart-lab data is missing or stale.
func NeedsRatingsRefresh(ctx context.Context, repo BondReferenceStore) bool {
	at, err := repo.RatingsScrapedAt(ctx)
	if err != nil || at.IsZero() {
		return true
	}
	return time.Since(at) > ratingsStaleAfter
}
