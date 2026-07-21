package persistence

import (
	"context"
	"sort"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
)

// FavoritesRepository is the SQL implementation of portfolio.FavoritesRepository.
type FavoritesRepository struct {
	db *DB
}

func NewFavoritesRepository(db *DB) *FavoritesRepository {
	return &FavoritesRepository{db: db}
}

func (r *FavoritesRepository) ListISINs(ctx context.Context, ownerTelegramID int64) ([]string, error) {
	var isins []string
	err := r.db.SelectContext(ctx, &isins, `SELECT isin FROM favorites WHERE owner_telegram_id = $1 ORDER BY added_at`, ownerTelegramID)
	return isins, err
}

func (r *FavoritesRepository) Add(ctx context.Context, ownerTelegramID int64, isin string) error {
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO favorites (owner_telegram_id, isin, added_at) VALUES ($1, $2, $3)
		ON CONFLICT(owner_telegram_id, isin) DO NOTHING
	`, ownerTelegramID, isin, time.Now().UTC().Format(time.RFC3339))
	return err
}

func (r *FavoritesRepository) Remove(ctx context.Context, ownerTelegramID int64, isin string) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM favorites WHERE owner_telegram_id = $1 AND isin = $2`, ownerTelegramID, isin)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

func (r *FavoritesRepository) SyncVisible(ctx context.Context, ownerTelegramID int64, isins map[string]struct{}) ([]string, error) {
	current, err := r.ListISINs(ctx, ownerTelegramID)
	if err != nil {
		return nil, err
	}
	var removed []string
	for _, isin := range current {
		if _, ok := isins[isin]; !ok {
			if _, err := r.Remove(ctx, ownerTelegramID, isin); err != nil {
				return nil, err
			}
			removed = append(removed, isin)
		}
	}
	sort.Strings(removed)
	return removed, nil
}

var _ portfolio.FavoritesRepository = (*FavoritesRepository)(nil)
