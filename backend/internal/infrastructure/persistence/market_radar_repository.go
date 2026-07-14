package persistence

import (
	"context"
	"database/sql"
	"encoding/json"

	"github.com/jmoiron/sqlx"
)

type MarketRadarRun struct {
	ID            string          `db:"id"`
	ScannedAt     string          `db:"scanned_at"`
	UniverseCount int             `db:"universe_count"`
	PayloadJSON   json.RawMessage `db:"payload_json"`
}

type MarketRadarRepository struct {
	db *sqlx.DB
}

func NewMarketRadarRepository(db *sqlx.DB) *MarketRadarRepository {
	return &MarketRadarRepository{db: db}
}

func (r *MarketRadarRepository) SaveRun(ctx context.Context, run MarketRadarRun) error {
	_, err := r.db.ExecContext(ctx, `
INSERT INTO market_radar_runs (id, scanned_at, universe_count, payload_json)
VALUES ($1, $2, $3, $4)
ON CONFLICT (id) DO UPDATE SET
  scanned_at = excluded.scanned_at,
  universe_count = excluded.universe_count,
  payload_json = excluded.payload_json
`,
		run.ID, run.ScannedAt, run.UniverseCount, run.PayloadJSON,
	)
	return err
}

func (r *MarketRadarRepository) GetLatest(ctx context.Context) (*MarketRadarRun, error) {
	var run MarketRadarRun
	err := r.db.GetContext(ctx, &run, `
SELECT id, scanned_at, universe_count, payload_json
FROM market_radar_runs
ORDER BY scanned_at DESC
LIMIT 1
`)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &run, nil
}
