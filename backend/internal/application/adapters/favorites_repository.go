package adapters

import (
	"context"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

// FavoritesRepository adapts persistence.FavoritesRepository to application.FavoritesRepository.
type FavoritesRepository struct {
	inner *persistence.FavoritesRepository
}

func NewFavoritesRepository(inner *persistence.FavoritesRepository) *FavoritesRepository {
	return &FavoritesRepository{inner: inner}
}

func (r *FavoritesRepository) ListISINs(ctx context.Context) ([]string, error) {
	return r.inner.ListISINs(ctx)
}

func (r *FavoritesRepository) Add(ctx context.Context, isin string) error {
	return r.inner.Add(ctx, isin)
}

func (r *FavoritesRepository) Remove(ctx context.Context, isin string) error {
	_, err := r.inner.Remove(ctx, isin)
	return err
}

var _ application.FavoritesRepository = (*FavoritesRepository)(nil)
