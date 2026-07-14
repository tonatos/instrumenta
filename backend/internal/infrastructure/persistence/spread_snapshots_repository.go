package persistence

import (
	"context"
	"time"

	"github.com/jmoiron/sqlx"
)

type SpreadSnapshot struct {
	ISIN          string   `db:"isin"`
	Date          string   `db:"date"`
	CreditSpreadPP float64 `db:"credit_spread_pp"`
	LastPricePct  *float64 `db:"last_price_pct"`
	Sector        string   `db:"sector"`
	RatingOrdinal *int     `db:"rating_ordinal"`
}

type SpreadSnapshotsRepository struct {
	db *sqlx.DB
}

func NewSpreadSnapshotsRepository(db *sqlx.DB) *SpreadSnapshotsRepository {
	return &SpreadSnapshotsRepository{db: db}
}

func (r *SpreadSnapshotsRepository) Upsert(ctx context.Context, snap SpreadSnapshot) error {
	_, err := r.db.ExecContext(ctx, `
INSERT INTO spread_snapshots (isin, date, credit_spread_pp, last_price_pct, sector, rating_ordinal)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (isin, date) DO UPDATE SET
  credit_spread_pp = excluded.credit_spread_pp,
  last_price_pct = excluded.last_price_pct,
  sector = excluded.sector,
  rating_ordinal = excluded.rating_ordinal
`,
		snap.ISIN, snap.Date, snap.CreditSpreadPP, snap.LastPricePct, snap.Sector, snap.RatingOrdinal,
	)
	return err
}

func (r *SpreadSnapshotsRepository) ListByISINsAndDate(ctx context.Context, isins []string, dateKey string) (map[string]SpreadSnapshot, error) {
	if len(isins) == 0 {
		return map[string]SpreadSnapshot{}, nil
	}
	query, args, err := sqlx.In(
		`SELECT isin, date, credit_spread_pp, last_price_pct, sector, rating_ordinal
         FROM spread_snapshots
         WHERE date = ? AND isin IN (?)`,
		dateKey, isins,
	)
	if err != nil {
		return nil, err
	}
	query = r.db.Rebind(query)
	var rows []SpreadSnapshot
	if err := r.db.SelectContext(ctx, &rows, query, args...); err != nil {
		return nil, err
	}
	out := make(map[string]SpreadSnapshot, len(rows))
	for _, r := range rows {
		out[r.ISIN] = r
	}
	return out, nil
}

func DateKey(t time.Time) string {
	return t.UTC().Format("2006-01-02")
}

