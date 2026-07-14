-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS market_radar_runs (
    id VARCHAR(32) PRIMARY KEY,
    scanned_at TIMESTAMPTZ NOT NULL,
    universe_count INTEGER NOT NULL,
    payload_json JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_radar_runs_scanned_at ON market_radar_runs(scanned_at DESC);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS market_radar_runs;
-- +goose StatementEnd
