package notifications

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

// AlertDetailKey returns the stable detail key for an alert.
func AlertDetailKey(alert Alert) string {
	return alert.DetailKey
}

// AlertFingerprint returns a deterministic fingerprint for deduplication.
func AlertFingerprint(alert Alert) string {
	return shared.StableID(alert.PortfolioID, string(alert.Kind), alert.ISIN+":"+alert.DetailKey)
}

// ShouldSendTelegram checks cooldown since the last Telegram delivery.
func ShouldSendTelegram(lastTelegramSentAt *time.Time, policy NotificationPolicy, now time.Time) bool {
	if lastTelegramSentAt == nil {
		return true
	}
	sent := lastTelegramSentAt.UTC()
	cooldown := time.Duration(policy.PutOfferTelegramCooldownHours) * time.Hour
	return now.UTC().Sub(sent) >= cooldown
}

// TelegramAllowedForAlert decides if an alert may be pushed to Telegram.
func TelegramAllowedForAlert(alert Alert, policy NotificationPolicy) bool {
	if alert.Kind == AlertKindPutOfferAction {
		return true
	}
	if alert.Kind == AlertKindRiskEscalation {
		order := map[AlertUrgency]int{AlertUrgencyNormal: 0, AlertUrgencySoon: 1, AlertUrgencyCritical: 2}
		return order[alert.Urgency] >= order[policy.RiskTelegramMinUrgency]
	}
	return false
}
