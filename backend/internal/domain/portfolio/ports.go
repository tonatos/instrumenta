package portfolio

import "context"

// Repository persists portfolio aggregates.
type Repository interface {
	ListAll(ctx context.Context) ([]Portfolio, error)
	ListByOwner(ctx context.Context, ownerTelegramID int64) ([]Portfolio, error)
	GetByID(ctx context.Context, portfolioID string) (*Portfolio, error)
	GetByIDForOwner(ctx context.Context, portfolioID string, ownerTelegramID int64) (*Portfolio, error)
	Save(ctx context.Context, portfolio Portfolio) (Portfolio, error)
	Delete(ctx context.Context, portfolioID string) (bool, error)
	DeleteForOwner(ctx context.Context, portfolioID string, ownerTelegramID int64) (bool, error)
}

// FavoritesRepository stores user favorite bond ISINs.
type FavoritesRepository interface {
	ListISINs(ctx context.Context, ownerTelegramID int64) ([]string, error)
	Add(ctx context.Context, ownerTelegramID int64, isin string) error
	Remove(ctx context.Context, ownerTelegramID int64, isin string) (bool, error)
	SyncVisible(ctx context.Context, ownerTelegramID int64, isins map[string]struct{}) ([]string, error)
}
