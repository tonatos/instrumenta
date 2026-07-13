package portfolio

import "context"

// Repository persists portfolio aggregates.
type Repository interface {
	ListAll(ctx context.Context) ([]Portfolio, error)
	GetByID(ctx context.Context, portfolioID string) (*Portfolio, error)
	Save(ctx context.Context, portfolio Portfolio) (Portfolio, error)
	Delete(ctx context.Context, portfolioID string) (bool, error)
}

// FavoritesRepository stores user favorite bond ISINs.
type FavoritesRepository interface {
	ListISINs(ctx context.Context) ([]string, error)
	Add(ctx context.Context, isin string) error
	Remove(ctx context.Context, isin string) (bool, error)
	SyncVisible(ctx context.Context, isins map[string]struct{}) ([]string, error)
}
