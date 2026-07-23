-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS billing_plan_versions (
    id TEXT PRIMARY KEY,
    catalog_group TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    period TEXT NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id TEXT PRIMARY KEY,
    owner_telegram_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    period TEXT NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    current_period_start TEXT NOT NULL,
    current_period_end TEXT NOT NULL,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    payment_method_id TEXT NOT NULL DEFAULT '',
    past_due_since TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_period_end
    ON billing_subscriptions(current_period_end);

CREATE TABLE IF NOT EXISTS billing_payments (
    id TEXT PRIMARY KEY,
    owner_telegram_id INTEGER NOT NULL,
    plan_version_id TEXT NOT NULL,
    period TEXT NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    yookassa_payment_id TEXT NOT NULL DEFAULT '',
    confirmation_url TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_billing_payments_owner
    ON billing_payments(owner_telegram_id);
CREATE INDEX IF NOT EXISTS idx_billing_payments_yookassa
    ON billing_payments(yookassa_payment_id);

CREATE TABLE IF NOT EXISTS billing_ledger (
    id TEXT PRIMARY KEY,
    owner_telegram_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    reason TEXT NOT NULL,
    payment_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_billing_ledger_owner_created
    ON billing_ledger(owner_telegram_id, created_at);

-- Seed current Pro tariff: 795 ₽/mo, 5940 ₽/yr (idempotent)
INSERT OR IGNORE INTO billing_plan_versions (
    id, catalog_group, code, period, amount_kopecks, features_json, effective_from, is_current
) VALUES (
    'pro_month_v1',
    'pro',
    'pro_month',
    'month',
    79500,
    '["broker_credentials.write","portfolio.attach","trading_portfolio.access"]',
    '2026-01-01T00:00:00Z',
    1
);
INSERT OR IGNORE INTO billing_plan_versions (
    id, catalog_group, code, period, amount_kopecks, features_json, effective_from, is_current
) VALUES (
    'pro_year_v1',
    'pro',
    'pro_year',
    'year',
    594000,
    '["broker_credentials.write","portfolio.attach","trading_portfolio.access"]',
    '2026-01-01T00:00:00Z',
    1
);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP TABLE IF EXISTS billing_ledger;
DROP TABLE IF EXISTS billing_payments;
DROP TABLE IF EXISTS billing_subscriptions;
DROP TABLE IF EXISTS billing_plan_versions;
-- +goose StatementEnd
