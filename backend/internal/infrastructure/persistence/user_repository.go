package persistence

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/tonatos/bond-monitor/backend/internal/domain/preferences"
)

// UserRepository persists Telegram users.
type UserRepository struct {
	db *DB
}

func NewUserRepository(db *DB) *UserRepository {
	return &UserRepository{db: db}
}

func (r *UserRepository) Upsert(ctx context.Context, telegramID int64, displayName string) error {
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO users (telegram_id, display_name, created_at, updated_at)
		VALUES ($1, $2, $3, $3)
		ON CONFLICT(telegram_id) DO UPDATE SET
			display_name = excluded.display_name,
			updated_at = excluded.updated_at
	`, telegramID, displayName, now)
	return err
}

// IsBotConnected reports whether the user has started a private chat with the bot.
func (r *UserRepository) IsBotConnected(ctx context.Context, telegramID int64) (bool, error) {
	var raw sql.NullString
	err := r.db.GetContext(ctx, &raw, `
		SELECT bot_connected_at FROM users WHERE telegram_id = $1
	`, telegramID)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return raw.Valid && raw.String != "", nil
}

// MarkBotConnected records /start (creates the user row if needed).
func (r *UserRepository) MarkBotConnected(ctx context.Context, telegramID int64, displayName string, at time.Time) error {
	if at.IsZero() {
		at = time.Now().UTC()
	}
	now := at.UTC().Format(time.RFC3339)
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO users (telegram_id, display_name, created_at, updated_at, bot_connected_at)
		VALUES ($1, $2, $3, $3, $3)
		ON CONFLICT(telegram_id) DO UPDATE SET
			display_name = CASE
				WHEN excluded.display_name = '' THEN users.display_name
				ELSE excluded.display_name
			END,
			bot_connected_at = excluded.bot_connected_at,
			updated_at = excluded.updated_at
	`, telegramID, displayName, now)
	return err
}

// MarkBotDisconnected clears opt-in (/stop or user blocked the bot).
func (r *UserRepository) MarkBotDisconnected(ctx context.Context, telegramID int64) error {
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := r.db.ExecContext(ctx, `
		UPDATE users SET bot_connected_at = NULL, updated_at = $2 WHERE telegram_id = $1
	`, telegramID, now)
	return err
}

// EnsureUsersNotifySchema adds bot_connected_at idempotently.
func EnsureUsersNotifySchema(ctx context.Context, db *sqlx.DB) error {
	if err := ensureColumn(ctx, db, "users", "bot_connected_at", "TEXT"); err != nil {
		return fmt.Errorf("users.bot_connected_at: %w", err)
	}
	return nil
}

// EnsureUsersTaxSchema adds tax_rate_pct idempotently.
func EnsureUsersTaxSchema(ctx context.Context, db *sqlx.DB) error {
	def := fmt.Sprintf("REAL NOT NULL DEFAULT %g", preferences.DefaultTaxRatePct)
	if err := ensureColumn(ctx, db, "users", "tax_rate_pct", def); err != nil {
		return fmt.Errorf("users.tax_rate_pct: %w", err)
	}
	return nil
}

// TaxRatePct returns the user's НДФЛ preference in percent points.
func (r *UserRepository) TaxRatePct(ctx context.Context, telegramID int64) (float64, error) {
	var pct sql.NullFloat64
	err := r.db.GetContext(ctx, &pct, `SELECT tax_rate_pct FROM users WHERE telegram_id = $1`, telegramID)
	if err == sql.ErrNoRows {
		return preferences.DefaultTaxRatePct, nil
	}
	if err != nil {
		return 0, err
	}
	if !pct.Valid {
		return preferences.DefaultTaxRatePct, nil
	}
	normalized, err := preferences.NormalizeTaxRatePct(pct.Float64)
	if err != nil {
		return preferences.DefaultTaxRatePct, nil
	}
	return normalized, nil
}

// SetTaxRatePct stores a validated НДФЛ preference (creates the user row if needed).
func (r *UserRepository) SetTaxRatePct(ctx context.Context, telegramID int64, pct float64) error {
	normalized, err := preferences.NormalizeTaxRatePct(pct)
	if err != nil {
		return err
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, err = r.db.ExecContext(ctx, `
		INSERT INTO users (telegram_id, display_name, created_at, updated_at, tax_rate_pct)
		VALUES ($1, '', $2, $2, $3)
		ON CONFLICT(telegram_id) DO UPDATE SET
			tax_rate_pct = excluded.tax_rate_pct,
			updated_at = excluded.updated_at
	`, telegramID, now, normalized)
	return err
}
