package notifications

import (
	"context"
	"time"
)

// NotificationRecord is the in-app notification read-model.
type NotificationRecord struct {
	ID          string
	Fingerprint string
	PortfolioID string
	Kind        string
	Payload     map[string]any
	Urgency     string
	CreatedAt   time.Time
	ReadAt      *time.Time
	DismissedAt *time.Time
}

func (n NotificationRecord) IsUnread() bool {
	return n.ReadAt == nil && n.DismissedAt == nil
}

// Repository stores user notifications.
type Repository interface {
	UpsertFromBus(ctx context.Context, fingerprint, portfolioID, kind string, payload map[string]any, urgency string, createdAt *time.Time) (NotificationRecord, error)
	ListForPortfolio(ctx context.Context, portfolioID string, unreadOnly bool) ([]NotificationRecord, error)
	GetByID(ctx context.Context, notificationID string) (*NotificationRecord, error)
	MarkRead(ctx context.Context, notificationID string) (*NotificationRecord, error)
	Dismiss(ctx context.Context, notificationID string) (*NotificationRecord, error)
}

// BusMessage is a notification event from Redis Stream.
type BusMessage struct {
	MessageID   string
	Fingerprint string
	PortfolioID string
	Kind        string
	Payload     map[string]any
	Urgency     string
	CreatedAt   string
}

// Bus publishes and consumes notification events.
type Bus interface {
	EnsureConsumerGroup(ctx context.Context) error
	Publish(ctx context.Context, fingerprint, portfolioID, kind string, payload map[string]any, urgency string) (string, error)
	ReadGroup(ctx context.Context, consumerName string, count int) ([]BusMessage, error)
	Ack(ctx context.Context, messageID string) error
	Ping(ctx context.Context) (bool, error)
}

// LedgerEntry tracks notifier delivery state.
type LedgerEntry struct {
	Fingerprint      string
	AlertKind        string
	PayloadJSON      string
	BusPublishedAt   *time.Time
	TelegramSentAt   *time.Time
	LastAttemptAt    *time.Time
	RetryCount       int
}

// LedgerRepository is the SQLite outbox for notifier delivery guarantees.
type LedgerRepository interface {
	EnsureDetected(fingerprint string, alert Alert) (bool, error)
	Get(fingerprint string) (*LedgerEntry, error)
	Count() (int, error)
	DeleteAll() (int, error)
	DeleteForPortfolio(portfolioID string) (int, error)
	MarkBusPublished(fingerprint string, at time.Time) (bool, error)
	MarkTelegramSent(fingerprint string, at time.Time) (bool, error)
	ListPendingBus() ([]LedgerEntry, error)
	ListPendingTelegram() ([]LedgerEntry, error)
}

// TelegramNotifier sends push messages via Telegram Bot API.
type TelegramNotifier interface {
	Configured() bool
	SendToChat(chatID int64, text string) bool
}
