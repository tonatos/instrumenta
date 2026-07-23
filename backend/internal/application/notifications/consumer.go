package notifications

import (
	"context"
	"log/slog"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/application"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

// Consumer reads Redis notification stream into SQLite read-model.
type Consumer struct {
	bus    *notifications.RedisBus
	repo   *persistence.NotificationsRepository
	name   string
	stop   chan struct{}
	done   chan struct{}
	logger *slog.Logger
}

func NewConsumer(redisURL string, repo *persistence.NotificationsRepository, logger *slog.Logger) *Consumer {
	return &Consumer{
		bus:    notifications.NewRedisBus(redisURL),
		repo:   repo,
		name:   "api-1",
		stop:   make(chan struct{}),
		done:   make(chan struct{}),
		logger: logger,
	}
}

func (c *Consumer) Start(ctx context.Context) error {
	if c.bus == nil || c.repo == nil {
		return nil
	}
	if err := c.bus.EnsureConsumerGroup(ctx); err != nil {
		if c.logger != nil {
			c.logger.Error("notification consumer group setup failed", "error", err)
		}
		return err
	}
	go c.loop(ctx)
	if c.logger != nil {
		c.logger.Info("notification consumer started")
	}
	return nil
}

func (c *Consumer) Stop(ctx context.Context) error {
	close(c.stop)
	select {
	case <-c.done:
	case <-ctx.Done():
	}
	return nil
}

func (c *Consumer) loop(ctx context.Context) {
	defer close(c.done)
	for {
		select {
		case <-c.stop:
			return
		case <-ctx.Done():
			return
		default:
		}
		messages, err := c.bus.ReadGroup(ctx, c.name, 20)
		if err != nil {
			if c.logger != nil {
				c.logger.Warn("notification consumer read failed", "error", err)
			}
			time.Sleep(2 * time.Second)
			continue
		}
		for _, msg := range messages {
			var createdAt *time.Time
			if msg.CreatedAt != "" {
				if t, err := time.Parse(time.RFC3339, msg.CreatedAt); err == nil {
					createdAt = &t
				}
			}
			if _, err := c.repo.UpsertFromBus(ctx, msg.Fingerprint, msg.PortfolioID, msg.Kind, msg.Payload, msg.Urgency, createdAt); err != nil {
				if c.logger != nil {
					c.logger.Warn("notification consumer upsert failed", "error", err)
				}
				continue
			}
			_ = c.bus.Ack(ctx, msg.MessageID)
		}
	}
}

var _ application.NotificationConsumer = (*Consumer)(nil)
