-- +goose Up
-- +goose StatementBegin
-- tax_rate_pct: personal НДФЛ preference (0 = ignore tax; else 13/15/18/20/22).
-- Applied idempotently via EnsureUsersTaxSchema for existing DBs.
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
-- Column drop is not replay-safe across SQLite/Postgres; leave for manual cleanup.
-- +goose StatementEnd
