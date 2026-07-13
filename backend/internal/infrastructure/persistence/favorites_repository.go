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

func (r *FavoritesRepository) ListISINs(ctx context.Context) ([]string, error) {
	var isins []string
	err := r.db.SelectContext(ctx, &isins, `SELECT isin FROM favorites ORDER BY added_at`)
	return isins, err
}

func (r *FavoritesRepository) Add(ctx context.Context, isin string) error {
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO favorites (isin, added_at) VALUES ($1, $2)
		ON CONFLICT(isin) DO NOTHING
	`, isin, time.Now().UTC().Format(time.RFC3339))
	return err
}

func (r *FavoritesRepository) Remove(ctx context.Context, isin string) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM favorites WHERE isin = $1`, isin)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

func (r *FavoritesRepository) SyncVisible(ctx context.Context, isins map[string]struct{}) ([]string, error) {
	current, err := r.ListISINs(ctx)
	if err != nil {
		return nil, err
	}
	var removed []string
	for _, isin := range current {
		if _, ok := isins[isin]; !ok {
			if _, err := r.Remove(ctx, isin); err != nil {
				return nil, err
			}
			removed = append(removed, isin)
		}
	}
	sort.Strings(removed)
	return removed, nil
}

var _ portfolio.FavoritesRepository = (*FavoritesRepository)(nil)
