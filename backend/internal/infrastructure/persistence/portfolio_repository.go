package persistence

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
)

// PortfolioRepository is the SQL implementation of portfolio.Repository.
type PortfolioRepository struct {
	db *DB
}

func NewPortfolioRepository(db *DB) *PortfolioRepository {
	return &PortfolioRepository{db: db}
}

func (r *PortfolioRepository) ListAll(ctx context.Context) ([]portfolio.Portfolio, error) {
	var rows []portfolioRow
	err := r.db.SelectContext(ctx, &rows, `SELECT id, name, created_at, updated_at, initial_amount_rub, horizon_date, risk_profile, cash_balance_rub, mode, account_id, account_kind, data FROM portfolios ORDER BY created_at`)
	if err != nil {
		return nil, err
	}
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

func (r *PortfolioRepository) GetByID(ctx context.Context, portfolioID string) (*portfolio.Portfolio, error) {
	var row portfolioRow
	err := r.db.GetContext(ctx, &row, `SELECT id, name, created_at, updated_at, initial_amount_rub, horizon_date, risk_profile, cash_balance_rub, mode, account_id, account_kind, data FROM portfolios WHERE id = $1`, portfolioID)
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
		INSERT INTO portfolios (id, name, created_at, updated_at, initial_amount_rub, horizon_date, risk_profile, cash_balance_rub, mode, account_id, account_kind, data)
		VALUES (:id, :name, :created_at, :updated_at, :initial_amount_rub, :horizon_date, :risk_profile, :cash_balance_rub, :mode, :account_id, :account_kind, :data)
		ON CONFLICT(id) DO UPDATE SET
			name = excluded.name, updated_at = excluded.updated_at,
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

var _ portfolio.Repository = (*PortfolioRepository)(nil)

// ApplyMigrations runs goose migrations from dir (for tests).
func ApplyMigrations(db *sqlx.DB, driver, migrationsDir string) error {
	// Inline schema for tests — avoids goose dependency in unit tests.
	schema := `
CREATE TABLE IF NOT EXISTS portfolios (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    initial_amount_rub REAL NOT NULL, horizon_date TEXT NOT NULL, risk_profile TEXT NOT NULL,
    cash_balance_rub REAL NOT NULL DEFAULT 0, mode TEXT NOT NULL DEFAULT 'simulation',
    account_id TEXT, account_kind TEXT, data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS favorites (isin TEXT PRIMARY KEY, added_at TEXT NOT NULL);
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
`
	_, err := db.Exec(schema)
	return err
}
