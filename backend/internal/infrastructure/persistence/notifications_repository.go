package persistence

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

// NotificationsRepository is the SQL implementation of notifications.Repository.
type NotificationsRepository struct {
	db *DB
}

func NewNotificationsRepository(db *DB) *NotificationsRepository {
	return &NotificationsRepository{db: db}
}

func (r *NotificationsRepository) UpsertFromBus(ctx context.Context, fingerprint, portfolioID, kind string, payload map[string]any, urgency string, createdAt *time.Time) (notifications.NotificationRecord, error) {
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return notifications.NotificationRecord{}, err
	}
	at := time.Now().UTC()
	if createdAt != nil {
		at = createdAt.UTC()
	}
	id := trading.StableID("notification", fingerprint, kind)
	row := userNotificationRow{
		ID: id, Fingerprint: fingerprint, PortfolioID: portfolioID,
		Kind: kind, PayloadJSON: string(payloadJSON), Urgency: urgency,
		CreatedAt: at.Format(time.RFC3339),
	}
	_, err = r.db.NamedExecContext(ctx, `
		INSERT INTO user_notifications (id, fingerprint, portfolio_id, kind, payload_json, urgency, created_at)
		VALUES (:id, :fingerprint, :portfolio_id, :kind, :payload_json, :urgency, :created_at)
		ON CONFLICT(fingerprint) DO UPDATE SET
			portfolio_id = excluded.portfolio_id, kind = excluded.kind,
			payload_json = excluded.payload_json, urgency = excluded.urgency
	`, row)
	if err != nil {
		return notifications.NotificationRecord{}, err
	}
	rec, err := r.GetByID(ctx, id)
	if err != nil || rec == nil {
		return notifications.NotificationRecord{}, err
	}
	return *rec, nil
}

func (r *NotificationsRepository) ListForPortfolio(ctx context.Context, portfolioID string, unreadOnly bool) ([]notifications.NotificationRecord, error) {
	query := `SELECT id, fingerprint, portfolio_id, kind, payload_json, urgency, created_at, read_at, dismissed_at FROM user_notifications WHERE portfolio_id = $1`
	if unreadOnly {
		query += ` AND read_at IS NULL AND dismissed_at IS NULL`
	}
	query += ` ORDER BY created_at DESC`
	var rows []userNotificationRow
	if err := r.db.SelectContext(ctx, &rows, query, portfolioID); err != nil {
		return nil, err
	}
	result := make([]notifications.NotificationRecord, 0, len(rows))
	for _, row := range rows {
		rec, err := notificationFromRow(row)
		if err != nil {
			return nil, err
		}
		result = append(result, rec)
	}
	return result, nil
}

func (r *NotificationsRepository) GetByID(ctx context.Context, notificationID string) (*notifications.NotificationRecord, error) {
	var row userNotificationRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, fingerprint, portfolio_id, kind, payload_json, urgency, created_at, read_at, dismissed_at
		FROM user_notifications WHERE id = $1
	`, notificationID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	rec, err := notificationFromRow(row)
	if err != nil {
		return nil, err
	}
	return &rec, nil
}

func (r *NotificationsRepository) MarkRead(ctx context.Context, notificationID string) (*notifications.NotificationRecord, error) {
	now := time.Now().UTC().Format(time.RFC3339)
	res, err := r.db.ExecContext(ctx, `UPDATE user_notifications SET read_at = $1 WHERE id = $2`, now, notificationID)
	if err != nil {
		return nil, err
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return nil, nil
	}
	return r.GetByID(ctx, notificationID)
}

func (r *NotificationsRepository) Dismiss(ctx context.Context, notificationID string) (*notifications.NotificationRecord, error) {
	now := time.Now().UTC().Format(time.RFC3339)
	res, err := r.db.ExecContext(ctx, `UPDATE user_notifications SET dismissed_at = $1 WHERE id = $2`, now, notificationID)
	if err != nil {
		return nil, err
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return nil, nil
	}
	return r.GetByID(ctx, notificationID)
}

func notificationFromRow(row userNotificationRow) (notifications.NotificationRecord, error) {
	var payload map[string]any
	if row.PayloadJSON != "" {
		if err := json.Unmarshal([]byte(row.PayloadJSON), &payload); err != nil {
			return notifications.NotificationRecord{}, err
		}
	}
	rec := notifications.NotificationRecord{
		ID: row.ID, Fingerprint: row.Fingerprint, PortfolioID: row.PortfolioID,
		Kind: row.Kind, Payload: payload, Urgency: row.Urgency,
		CreatedAt: parseDBTime(row.CreatedAt),
	}
	if row.ReadAt.Valid {
		t := parseDBTime(row.ReadAt.String)
		rec.ReadAt = &t
	}
	if row.DismissedAt.Valid {
		t := parseDBTime(row.DismissedAt.String)
		rec.DismissedAt = &t
	}
	return rec, nil
}

var _ notifications.Repository = (*NotificationsRepository)(nil)
