package persistence

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
)

const portfolioSelectCols = `id, name, created_at, updated_at, owner_telegram_id, initial_amount_rub, horizon_date, risk_profile, cash_balance_rub, mode, account_id, account_kind, data`

// PortfolioRepository is the SQL implementation of portfolio.Repository.
type PortfolioRepository struct {
	db *DB
}

func NewPortfolioRepository(db *DB) *PortfolioRepository {
	return &PortfolioRepository{db: db}
}

func (r *PortfolioRepository) ListAll(ctx context.Context) ([]portfolio.Portfolio, error) {
	var rows []portfolioRow
	err := r.db.SelectContext(ctx, &rows, `SELECT `+portfolioSelectCols+` FROM portfolios ORDER BY created_at`)
	if err != nil {
		return nil, err
	}
	return portfoliosFromRows(rows)
}

func (r *PortfolioRepository) ListByOwner(ctx context.Context, ownerTelegramID int64) ([]portfolio.Portfolio, error) {
	var rows []portfolioRow
	err := r.db.SelectContext(ctx, &rows, `SELECT `+portfolioSelectCols+` FROM portfolios WHERE owner_telegram_id = $1 ORDER BY created_at`, ownerTelegramID)
	if err != nil {
		return nil, err
	}
	return portfoliosFromRows(rows)
}

func (r *PortfolioRepository) GetByID(ctx context.Context, portfolioID string) (*portfolio.Portfolio, error) {
	var row portfolioRow
	err := r.db.GetContext(ctx, &row, `SELECT `+portfolioSelectCols+` FROM portfolios WHERE id = $1`, portfolioID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := portfolioFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (r *PortfolioRepository) GetByIDForOwner(ctx context.Context, portfolioID string, ownerTelegramID int64) (*portfolio.Portfolio, error) {
	var row portfolioRow
	err := r.db.GetContext(ctx, &row, `SELECT `+portfolioSelectCols+` FROM portfolios WHERE id = $1 AND owner_telegram_id = $2`, portfolioID, ownerTelegramID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := portfolioFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (r *PortfolioRepository) Save(ctx context.Context, p portfolio.Portfolio) (portfolio.Portfolio, error) {
	data, err := portfolioToDataJSON(p)
	if err != nil {
		return portfolio.Portfolio{}, err
	}
	if p.CreatedAt == "" {
		p.CreatedAt = time.Now().UTC().Format(time.RFC3339)
	}
	p.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	row := portfolioRow{
		ID: p.ID, Name: p.Name, CreatedAt: p.CreatedAt, UpdatedAt: p.UpdatedAt,
		OwnerTelegramID: p.OwnerTelegramID,
		InitialAmountRub: p.InitialAmountRub, HorizonDate: p.HorizonDate.Format("2006-01-02"),
		RiskProfile: string(p.RiskProfile), CashBalanceRub: p.CashBalanceRub,
		Mode: string(p.Mode), Data: string(data),
	}
	if p.AccountID != nil {
		row.AccountID = sql.NullString{String: *p.AccountID, Valid: true}
	}
	if p.AccountKind != nil {
		row.AccountKind = sql.NullString{String: string(*p.AccountKind), Valid: true}
	}
	_, err = r.db.NamedExecContext(ctx, `
		INSERT INTO portfolios (id, name, created_at, updated_at, owner_telegram_id, initial_amount_rub, horizon_date, risk_profile, cash_balance_rub, mode, account_id, account_kind, data)
		VALUES (:id, :name, :created_at, :updated_at, :owner_telegram_id, :initial_amount_rub, :horizon_date, :risk_profile, :cash_balance_rub, :mode, :account_id, :account_kind, :data)
		ON CONFLICT(id) DO UPDATE SET
			name = excluded.name, updated_at = excluded.updated_at,
			owner_telegram_id = excluded.owner_telegram_id,
			initial_amount_rub = excluded.initial_amount_rub, horizon_date = excluded.horizon_date,
			risk_profile = excluded.risk_profile, cash_balance_rub = excluded.cash_balance_rub,
			mode = excluded.mode, account_id = excluded.account_id, account_kind = excluded.account_kind,
			data = excluded.data
	`, row)
	if err != nil {
		return portfolio.Portfolio{}, err
	}
	return p, nil
}

func (r *PortfolioRepository) Delete(ctx context.Context, portfolioID string) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM portfolios WHERE id = $1`, portfolioID)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

func (r *PortfolioRepository) DeleteForOwner(ctx context.Context, portfolioID string, ownerTelegramID int64) (bool, error) {
	res, err := r.db.ExecContext(ctx, `DELETE FROM portfolios WHERE id = $1 AND owner_telegram_id = $2`, portfolioID, ownerTelegramID)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

func portfoliosFromRows(rows []portfolioRow) ([]portfolio.Portfolio, error) {
	result := make([]portfolio.Portfolio, 0, len(rows))
	for _, row := range rows {
		p, err := portfolioFromRow(row)
		if err != nil {
			return nil, err
		}
		result = append(result, p)
	}
	return result, nil
}

var _ portfolio.Repository = (*PortfolioRepository)(nil)

// EnsureMultiTenantSchema adds owner columns / favorites reshaping idempotently.
// Legacy rows without an owner get DEFAULT 1 (synthetic); real ownership is set at write time.
func EnsureMultiTenantSchema(ctx context.Context, db *sqlx.DB) error {
	const legacyOwnerTelegramID int64 = 1
	if err := ensureColumn(ctx, db, "portfolios", "owner_telegram_id", fmt.Sprintf("BIGINT NOT NULL DEFAULT %d", legacyOwnerTelegramID)); err != nil {
		return err
	}
	if _, err := db.ExecContext(ctx, `CREATE INDEX IF NOT EXISTS idx_portfolios_owner ON portfolios(owner_telegram_id)`); err != nil {
		return err
	}
	if err := migrateFavoritesToMultiTenant(ctx, db, legacyOwnerTelegramID); err != nil {
		return err
	}
	return nil
}

func ensureColumn(ctx context.Context, db *sqlx.DB, table, column, decl string) error {
	var count int
	err := db.GetContext(ctx, &count, `
		SELECT COUNT(*) FROM pragma_table_info($1) WHERE name = $2
	`, table, column)
	if err != nil {
		// Postgres: information_schema
		err2 := db.GetContext(ctx, &count, `
			SELECT COUNT(*) FROM information_schema.columns
			WHERE table_name = $1 AND column_name = $2
		`, table, column)
		if err2 != nil {
			return fmt.Errorf("check column %s.%s: %v / %v", table, column, err, err2)
		}
	}
	if count > 0 {
		return nil
	}
	_, err = db.ExecContext(ctx, fmt.Sprintf(`ALTER TABLE %s ADD COLUMN %s %s`, table, column, decl))
	if err != nil && !isDuplicateColumnErr(err) {
		return err
	}
	return nil
}

func isDuplicateColumnErr(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "duplicate column") || strings.Contains(msg, "already exists")
}

func migrateFavoritesToMultiTenant(ctx context.Context, db *sqlx.DB, backfillTelegramID int64) error {
	var hasOwner int
	_ = db.GetContext(ctx, &hasOwner, `SELECT COUNT(*) FROM pragma_table_info('favorites') WHERE name = 'owner_telegram_id'`)
	if hasOwner > 0 {
		return nil
	}
	// Postgres check
	_ = db.GetContext(ctx, &hasOwner, `
		SELECT COUNT(*) FROM information_schema.columns
		WHERE table_name = 'favorites' AND column_name = 'owner_telegram_id'
	`)
	if hasOwner > 0 {
		return nil
	}

	_, err := db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS favorites_mt (
			owner_telegram_id BIGINT NOT NULL,
			isin TEXT NOT NULL,
			added_at TEXT NOT NULL,
			PRIMARY KEY (owner_telegram_id, isin)
		)
	`)
	if err != nil {
		return err
	}
	_, err = db.ExecContext(ctx, `
		INSERT OR IGNORE INTO favorites_mt (owner_telegram_id, isin, added_at)
		SELECT $1, isin, added_at FROM favorites
	`, backfillTelegramID)
	if err != nil {
		// Postgres
		_, err = db.ExecContext(ctx, `
			INSERT INTO favorites_mt (owner_telegram_id, isin, added_at)
			SELECT $1, isin, added_at FROM favorites
			ON CONFLICT DO NOTHING
		`, backfillTelegramID)
		if err != nil {
			return err
		}
	}
	_, _ = db.ExecContext(ctx, `DROP TABLE IF EXISTS favorites`)
	_, err = db.ExecContext(ctx, `ALTER TABLE favorites_mt RENAME TO favorites`)
	return err
}

// ApplyMigrations runs inline schema for tests.
func ApplyMigrations(db *sqlx.DB, driver, migrationsDir string) error {
	_ = driver
	_ = migrationsDir
	schema := `
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    bot_connected_at TEXT
);
CREATE TABLE IF NOT EXISTS portfolios (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    owner_telegram_id INTEGER NOT NULL DEFAULT 1,
    initial_amount_rub REAL NOT NULL, horizon_date TEXT NOT NULL, risk_profile TEXT NOT NULL,
    cash_balance_rub REAL NOT NULL DEFAULT 0, mode TEXT NOT NULL DEFAULT 'simulation',
    account_id TEXT, account_kind TEXT, data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS favorites (
    owner_telegram_id INTEGER NOT NULL,
    isin TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (owner_telegram_id, isin)
);
CREATE TABLE IF NOT EXISTS broker_credentials (
    id TEXT PRIMARY KEY,
    owner_telegram_id INTEGER NOT NULL,
    account_kind TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    dek_wrapped BLOB NOT NULL,
    nonce BLOB NOT NULL,
    kek_version INTEGER NOT NULL DEFAULT 1,
    fingerprint TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_telegram_id, account_kind)
);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_notifications (
    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, portfolio_id TEXT NOT NULL,
    kind TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', urgency TEXT NOT NULL,
    created_at TEXT NOT NULL, read_at TEXT, dismissed_at TEXT
);
CREATE TABLE IF NOT EXISTS deploy_sessions (
    id TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL, status TEXT NOT NULL,
    cash_snapshot_rub REAL NOT NULL, items_json TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS spread_snapshots (
    isin TEXT NOT NULL,
    date TEXT NOT NULL,
    credit_spread_pp REAL NOT NULL,
    last_price_pct REAL,
    sector TEXT NOT NULL DEFAULT '',
    rating_ordinal INTEGER,
    PRIMARY KEY (isin, date)
);
CREATE TABLE IF NOT EXISTS market_radar_runs (
    id TEXT PRIMARY KEY,
    scanned_at TEXT NOT NULL,
    universe_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bond_credit_ratings (
    isin TEXT PRIMARY KEY,
    rating TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bond_default_flags (
    isin TEXT PRIMARY KEY,
    has_default INTEGER NOT NULL DEFAULT 0,
    has_technical_default INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issuer_rating_patterns (
    pattern TEXT PRIMARY KEY,
    rating TEXT NOT NULL
);
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
CREATE TABLE IF NOT EXISTS billing_ledger (
    id TEXT PRIMARY KEY,
    owner_telegram_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount_kopecks INTEGER NOT NULL,
    reason TEXT NOT NULL,
    payment_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
`
	if _, err := db.Exec(schema); err != nil {
		return err
	}
	_, err := db.Exec(`
INSERT OR IGNORE INTO billing_plan_versions (
    id, catalog_group, code, period, amount_kopecks, features_json, effective_from, is_current
) VALUES
('pro_month_v1','pro','pro_month','month',79500,'["broker_credentials.write","portfolio.attach","trading_portfolio.access"]','2026-01-01T00:00:00Z',1),
('pro_year_v1','pro','pro_year','year',594000,'["broker_credentials.write","portfolio.attach","trading_portfolio.access"]','2026-01-01T00:00:00Z',1)
`)
	return err
}
