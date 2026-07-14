-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS spread_snapshots (
    isin VARCHAR(16) NOT NULL,
    date DATE NOT NULL,
    credit_spread_pp DOUBLE PRECISION NOT NULL,
    last_price_pct DOUBLE PRECISION,
    sector VARCHAR(64) NOT NULL DEFAULT '',
    rating_ordinal INTEGER,
    PRIMARY KEY (isin, date)
);
CREATE INDEX IF NOT EXISTS idx_spread_snapshots_date ON spread_snapshots(date);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS spread_snapshots;
-- +goose StatementEnd

