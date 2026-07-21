-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_credentials (
    id VARCHAR(32) PRIMARY KEY,
    owner_telegram_id BIGINT NOT NULL,
    account_kind VARCHAR(32) NOT NULL,
    ciphertext BLOB NOT NULL,
    dek_wrapped BLOB NOT NULL,
    nonce BLOB NOT NULL,
    kek_version INTEGER NOT NULL DEFAULT 1,
    fingerprint VARCHAR(32) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (owner_telegram_id, account_kind)
);
CREATE INDEX IF NOT EXISTS idx_broker_credentials_owner ON broker_credentials(owner_telegram_id);

-- portfolios.owner_telegram_id and favorites multi-tenant shape are applied
-- idempotently in Go (ensureMultiTenantSchema) because ALTER is not replay-safe.
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS broker_credentials;
DROP TABLE IF EXISTS users;
-- +goose StatementEnd
