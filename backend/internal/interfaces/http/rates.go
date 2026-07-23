package httpapi

import (
	"context"

	appmarket "github.com/tonatos/bond-monitor/backend/internal/application/market"
	"github.com/tonatos/bond-monitor/backend/internal/domain/preferences"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

// resolveMarketRates returns key rate (pp) and tax fraction for the request tenant.
func (h *Handler) resolveMarketRates(ctx context.Context) (keyRatePP, taxFraction float64) {
	keyRatePP = appmarket.DefaultKeyRateFallback
	if h.deps.KeyRates != nil {
		keyRatePP = h.deps.KeyRates.Current(ctx)
	}
	taxPct := preferences.DefaultTaxRatePct
	if owner, ok := auth.OwnerTelegramID(ctx); ok && h.deps.Users != nil {
		if pct, err := h.deps.Users.TaxRatePct(ctx, owner); err == nil {
			taxPct = pct
		}
	}
	return keyRatePP, preferences.TaxRateFraction(taxPct)
}
