package adapters

import (
	"context"

	"github.com/tonatos/instrumenta/backend/internal/application"
	domain "github.com/tonatos/instrumenta/backend/internal/domain/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

// NotificationsRepository adapts persistence.NotificationsRepository to application.NotificationsRepository.
type NotificationsRepository struct {
	inner *persistence.NotificationsRepository
}

func NewNotificationsRepository(inner *persistence.NotificationsRepository) *NotificationsRepository {
	return &NotificationsRepository{inner: inner}
}

func (r *NotificationsRepository) ListForPortfolio(ctx context.Context, portfolioID string, unreadOnly bool) ([]application.NotificationRecord, error) {
	records, err := r.inner.ListForPortfolio(ctx, portfolioID, unreadOnly)
	if err != nil {
		return nil, err
	}
	out := make([]application.NotificationRecord, 0, len(records))
	for _, rec := range records {
		out = append(out, toApplicationNotification(rec))
	}
	return out, nil
}

func (r *NotificationsRepository) MarkRead(ctx context.Context, notificationID string) (*application.NotificationRecord, error) {
	rec, err := r.inner.MarkRead(ctx, notificationID)
	if err != nil || rec == nil {
		return nil, err
	}
	appRec := toApplicationNotification(*rec)
	return &appRec, nil
}

func (r *NotificationsRepository) Dismiss(ctx context.Context, notificationID string) (*application.NotificationRecord, error) {
	rec, err := r.inner.Dismiss(ctx, notificationID)
	if err != nil || rec == nil {
		return nil, err
	}
	appRec := toApplicationNotification(*rec)
	return &appRec, nil
}

func toApplicationNotification(rec domain.NotificationRecord) application.NotificationRecord {
	return application.NotificationRecord{
		ID:          rec.ID,
		Fingerprint: rec.Fingerprint,
		PortfolioID: rec.PortfolioID,
		Kind:        rec.Kind,
		Payload:     rec.Payload,
		Urgency:     rec.Urgency,
		CreatedAt:   rec.CreatedAt,
		ReadAt:      rec.ReadAt,
		DismissedAt: rec.DismissedAt,
		IsUnread:    rec.IsUnread(),
	}
}

var _ application.NotificationsRepository = (*NotificationsRepository)(nil)
