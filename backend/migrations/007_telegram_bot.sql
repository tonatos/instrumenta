-- +goose Up
-- +goose StatementBegin
-- bot_connected_at: user pressed Start in Telegram (required for Bot API push).
-- Applied idempotently via EnsureUsersNotifySchema for existing DBs.
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
-- Column drop is not replay-safe across SQLite/Postgres; leave for manual cleanup.
-- +goose StatementEnd
