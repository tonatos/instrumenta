-- +goose Up
-- +goose StatementBegin
-- trade_enabled / trade_capability_checked: applied idempotently via EnsureBrokerCredentialsTradeSchema.
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
-- Column drop is not replay-safe across SQLite/Postgres; leave for manual cleanup.
-- +goose StatementEnd
