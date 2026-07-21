package adapters

import (
	"context"
	"fmt"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

// FavoritesRepository adapts persistence.FavoritesRepository to application.FavoritesRepository.
type FavoritesRepository struct {
	inner *persistence.FavoritesRepository
}

func NewFavoritesRepository(inner *persistence.FavoritesRepository) *FavoritesRepository {
	return &FavoritesRepository{inner: inner}
}

func (r *FavoritesRepository) ListISINs(ctx context.Context) ([]string, error) {
	owner, ok := auth.OwnerTelegramID(ctx)
	if !ok {
		return nil, fmt.Errorf("owner required")
	}
	return r.inner.ListISINs(ctx, owner)
}

func (r *FavoritesRepository) Add(ctx context.Context, isin string) error {
	owner, ok := auth.OwnerTelegramID(ctx)
	if !ok {
		return fmt.Errorf("owner required")
	}
	return r.inner.Add(ctx, owner, isin)
}

func (r *FavoritesRepository) Remove(ctx context.Context, isin string) error {
	owner, ok := auth.OwnerTelegramID(ctx)
	if !ok {
		return fmt.Errorf("owner required")
	}
	_, err := r.inner.Remove(ctx, owner, isin)
	return err
}

var _ application.FavoritesRepository = (*FavoritesRepository)(nil)
