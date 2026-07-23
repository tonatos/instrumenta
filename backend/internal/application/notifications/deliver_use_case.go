package notifications

import (
	"context"
	"encoding/json"
	"time"

	domain "github.com/tonatos/instrumenta/backend/internal/domain/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/notifications"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
)

// TelegramDeliveryGate decides whether the owner may receive Telegram push.
type TelegramDeliveryGate interface {
	CanReceiveTelegram(ctx context.Context, ownerTelegramID int64) bool
}

// DeliverUseCase publishes alerts to bus, ledger, and Telegram.
type DeliverUseCase struct {
	ledger   *notifications.LedgerRepository
	bus      *notifications.RedisBus
	telegram *notifications.TelegramClient
	repo     *persistence.NotificationsRepository
	gate     TelegramDeliveryGate
	policy   domain.NotificationPolicy
}

func NewDeliverUseCase(
	ledger *notifications.LedgerRepository,
	bus *notifications.RedisBus,
	telegram *notifications.TelegramClient,
	repo *persistence.NotificationsRepository,
	gate TelegramDeliveryGate,
) *DeliverUseCase {
	return &DeliverUseCase{
		ledger: ledger, bus: bus, telegram: telegram, repo: repo, gate: gate,
		policy: domain.DefaultNotificationPolicy,
	}
}

func (d *DeliverUseCase) ProcessAlert(ctx context.Context, alert domain.Alert, portfolioName string, ownerTelegramID int64) error {
	fingerprint := domain.AlertFingerprint(alert)
	if _, err := d.ledger.EnsureDetected(fingerprint, alert); err != nil {
		return err
	}
	if err := d.publishBus(ctx, fingerprint, alert); err != nil {
		return err
	}
	d.sendTelegramIfNeeded(ctx, fingerprint, alert, portfolioName, ownerTelegramID)
	return nil
}

func (d *DeliverUseCase) RetryPending(ctx context.Context, portfolioNames map[string]string, ownerByPortfolio map[string]int64) error {
	pendingBus, err := d.ledger.ListPendingBus()
	if err != nil {
		return err
	}
	for _, entry := range pendingBus {
		alert, err := alertFromLedger(entry)
		if err != nil {
			continue
		}
		_ = d.publishBus(ctx, entry.Fingerprint, alert)
	}
	pendingTG, err := d.ledger.ListPendingTelegram()
	if err != nil {
		return err
	}
	for _, entry := range pendingTG {
		alert, err := alertFromLedger(entry)
		if err != nil {
			continue
		}
		name := portfolioNames[alert.PortfolioID]
		if name == "" {
			name = alert.PortfolioID
		}
		d.sendTelegramIfNeeded(ctx, entry.Fingerprint, alert, name, ownerByPortfolio[alert.PortfolioID])
	}
	return nil
}

func (d *DeliverUseCase) publishBus(ctx context.Context, fingerprint string, alert domain.Alert) error {
	entry, _ := d.ledger.Get(fingerprint)
	if entry != nil && entry.BusPublishedAt != nil {
		return nil
	}
	now := time.Now().UTC()
	payload := alertPayload(alert)
	published := false
	if d.bus != nil {
		if _, err := d.bus.Publish(ctx, fingerprint, alert.PortfolioID, string(alert.Kind), payload, string(alert.Urgency)); err == nil {
			published = true
		}
	}
	if !published && d.repo != nil {
		if _, err := d.repo.UpsertFromBus(ctx, fingerprint, alert.PortfolioID, string(alert.Kind), payload, string(alert.Urgency), &now); err != nil {
			return err
		}
	}
	if published || d.repo != nil {
		_, _ = d.ledger.MarkBusPublished(fingerprint, now)
	}
	return nil
}

func (d *DeliverUseCase) sendTelegramIfNeeded(ctx context.Context, fingerprint string, alert domain.Alert, portfolioName string, ownerTelegramID int64) {
	if d.telegram == nil || !d.telegram.Configured() || !domain.TelegramAllowedForAlert(alert, d.policy) {
		return
	}
	if ownerTelegramID == 0 {
		return
	}
	if d.gate != nil && !d.gate.CanReceiveTelegram(ctx, ownerTelegramID) {
		return
	}
	entry, _ := d.ledger.Get(fingerprint)
	var lastSent *time.Time
	if entry != nil {
		lastSent = entry.TelegramSentAt
	}
	if !domain.ShouldSendTelegram(lastSent, d.policy, time.Now()) {
		return
	}
	prefix := "🟡"
	if alert.Urgency == domain.AlertUrgencyCritical {
		prefix = "🔴"
	}
	text := prefix + " " + portfolioName + "\n" + alert.Name + " (" + alert.ISIN + ")\n" + alert.Reason
	if d.telegram.SendToChat(ownerTelegramID, text) {
		_, _ = d.ledger.MarkTelegramSent(fingerprint, time.Now().UTC())
	}
}

func alertPayload(alert domain.Alert) map[string]any {
	payload := map[string]any{
		"portfolio_id": alert.PortfolioID,
		"kind":         string(alert.Kind),
		"isin":         alert.ISIN,
		"name":         alert.Name,
		"reason":       alert.Reason,
		"urgency":      string(alert.Urgency),
	}
	if alert.ExtraPayload != nil {
		for k, v := range alert.ExtraPayload {
			if _, exists := payload[k]; exists {
				continue
			}
			payload[k] = v
		}
	}
	if alert.FIGI != nil {
		payload["figi"] = *alert.FIGI
	}
	if alert.SuggestedPricePct != nil {
		payload["suggested_price_pct"] = *alert.SuggestedPricePct
	}
	if alert.MarketPricePct != nil {
		payload["market_price_pct"] = *alert.MarketPricePct
	}
	if alert.Lots > 0 {
		payload["lots"] = alert.Lots
	}
	if alert.DueDate != nil {
		payload["due_date"] = alert.DueDate.Format("2006-01-02")
	}
	return payload
}

func alertFromLedger(entry domain.LedgerEntry) (domain.Alert, error) {
	var payload map[string]any
	if err := json.Unmarshal([]byte(entry.PayloadJSON), &payload); err != nil {
		return domain.Alert{}, err
	}
	alert := domain.Alert{
		PortfolioID: str(payload["portfolio_id"]),
		Kind:        domain.AlertKind(str(payload["kind"])),
		ISIN:        str(payload["isin"]),
		Name:        str(payload["name"]),
		Reason:      str(payload["reason"]),
		Urgency:     domain.AlertUrgency(str(payload["urgency"])),
	}
	if figi, ok := payload["figi"].(string); ok {
		alert.FIGI = &figi
	}
	if due, ok := payload["due_date"].(string); ok {
		if t, err := time.Parse("2006-01-02", due); err == nil {
			alert.DueDate = &t
		}
	}
	return alert, nil
}

func str(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
