package notifications

import (
	"context"
	"encoding/json"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
)

const (
	streamKey      = "bond-monitor:notifications"
	consumerGroup  = "api"
)

// RedisBus implements notifications.Bus via Redis Streams.
type RedisBus struct {
	client *redis.Client
}

func NewRedisBus(redisURL string) *RedisBus {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		opts = &redis.Options{Addr: redisURL}
	}
	return &RedisBus{client: redis.NewClient(opts)}
}

func (b *RedisBus) EnsureConsumerGroup(ctx context.Context) error {
	err := b.client.XGroupCreateMkStream(ctx, streamKey, consumerGroup, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		return err
	}
	return nil
}

func (b *RedisBus) Publish(ctx context.Context, fingerprint, portfolioID, kind string, payload map[string]any, urgency string) (string, error) {
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	createdAt := time.Now().UTC().Format(time.RFC3339)
	return b.client.XAdd(ctx, &redis.XAddArgs{
		Stream: streamKey,
		Values: map[string]any{
			"fingerprint":  fingerprint,
			"portfolio_id": portfolioID,
			"kind":         kind,
			"payload":      string(payloadJSON),
			"urgency":      urgency,
			"created_at":   createdAt,
		},
	}).Result()
}

func (b *RedisBus) ReadGroup(ctx context.Context, consumerName string, count int) ([]notifications.BusMessage, error) {
	entries, err := b.client.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    consumerGroup,
		Consumer: consumerName,
		Streams:  []string{streamKey, ">"},
		Count:    int64(count),
		Block:    time.Second,
	}).Result()
	if err == redis.Nil {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var messages []notifications.BusMessage
	for _, stream := range entries {
		for _, item := range stream.Messages {
			payload := map[string]any{}
			if raw, ok := item.Values["payload"].(string); ok {
				_ = json.Unmarshal([]byte(raw), &payload)
			}
			messages = append(messages, notifications.BusMessage{
				MessageID:   item.ID,
				Fingerprint: strVal(item.Values["fingerprint"]),
				PortfolioID: strVal(item.Values["portfolio_id"]),
				Kind:        strVal(item.Values["kind"]),
				Payload:     payload,
				Urgency:     strVal(item.Values["urgency"]),
				CreatedAt:   strVal(item.Values["created_at"]),
			})
		}
	}
	return messages, nil
}

func (b *RedisBus) Ack(ctx context.Context, messageID string) error {
	return b.client.XAck(ctx, streamKey, consumerGroup, messageID).Err()
}

func (b *RedisBus) Ping(ctx context.Context) (bool, error) {
	res, err := b.client.Ping(ctx).Result()
	return res == "PONG", err
}

func strVal(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

var _ notifications.Bus = (*RedisBus)(nil)
