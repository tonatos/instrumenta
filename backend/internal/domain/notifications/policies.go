package notifications

// NotificationPolicy controls alert delivery behavior.
type NotificationPolicy struct {
	PutOfferTelegramCooldownHours int
	RiskTelegramMinUrgency        AlertUrgency
	IncludePutOfferWatchInAlerts  bool
}

var DefaultNotificationPolicy = NotificationPolicy{
	PutOfferTelegramCooldownHours: 24,
	RiskTelegramMinUrgency:        AlertUrgencyCritical,
	IncludePutOfferWatchInAlerts:  false,
}

// TelegramUrgencyAllowed returns whether urgency qualifies for Telegram in legacy policy.
func TelegramUrgencyAllowed(urgency AlertUrgency) bool {
	return urgency == AlertUrgencyCritical
}
