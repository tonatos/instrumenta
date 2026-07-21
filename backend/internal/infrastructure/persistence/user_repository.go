package persistence

import (
	"context"
	"time"
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
