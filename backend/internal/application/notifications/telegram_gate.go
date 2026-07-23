package notifications

import (
	"context"

	appbilling "github.com/tonatos/bond-monitor/backend/internal/application/billing"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

// SubscriptionTelegramGate requires Pro (or complimentary) + bot /start opt-in.
type SubscriptionTelegramGate struct {
	Users   *persistence.UserRepository
	Billing *appbilling.Service
}

func (g *SubscriptionTelegramGate) CanReceiveTelegram(ctx context.Context, ownerTelegramID int64) bool {
	if g == nil || g.Users == nil || g.Billing == nil || ownerTelegramID == 0 {
		return false
	}
	connected, err := g.Users.IsBotConnected(ctx, ownerTelegramID)
	if err != nil || !connected {
		return false
	}
	status, err := g.Billing.GetStatus(ctx, ownerTelegramID)
	if err != nil {
		return false
	}
	return status.HasActiveAccess || status.Complimentary
}
