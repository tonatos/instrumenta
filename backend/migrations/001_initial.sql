-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS portfolios (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    initial_amount_rub DOUBLE PRECISION NOT NULL,
    horizon_date DATE NOT NULL,
    risk_profile VARCHAR(32) NOT NULL,
    cash_balance_rub DOUBLE PRECISION NOT NULL DEFAULT 0,
    mode VARCHAR(32) NOT NULL DEFAULT 'simulation',
    account_id VARCHAR(64),
    account_kind VARCHAR(32),
    data JSON NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS favorites (
    isin VARCHAR(16) PRIMARY KEY,
    added_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_notifications (
    id VARCHAR(32) PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    portfolio_id VARCHAR(32) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    payload_json JSON NOT NULL DEFAULT '{}',
    urgency VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    read_at TIMESTAMPTZ,
    dismissed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_notifications_portfolio_id ON user_notifications(portfolio_id);

CREATE TABLE IF NOT EXISTS deploy_sessions (
    id VARCHAR(32) PRIMARY KEY,
    portfolio_id VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    cash_snapshot_rub DOUBLE PRECISION NOT NULL,
    items_json JSON NOT NULL,
    warnings_json JSON NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_deploy_sessions_portfolio_id ON deploy_sessions(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_deploy_sessions_expires_at ON deploy_sessions(expires_at);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS deploy_sessions;
DROP TABLE IF EXISTS user_notifications;
DROP TABLE IF EXISTS app_settings;
DROP TABLE IF EXISTS favorites;
DROP TABLE IF EXISTS portfolios;
-- +goose StatementEnd
