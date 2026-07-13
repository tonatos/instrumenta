package trading

import (
	"strconv"

	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

// DeploySessionPolicy controls TTL and staleness thresholds for frozen plans.
type DeploySessionPolicy struct {
	TTLHours            int
	PriceDriftWarnPct   float64
	PriceDriftStalePct  float64
}

func DefaultDeploySessionPolicy() DeploySessionPolicy {
	return DeploySessionPolicy{
		TTLHours:           24,
		PriceDriftWarnPct:  1.5,
		PriceDriftStalePct: 5.0,
	}
}

const (
	buyLimitPriceBufferSandbox    = 0.005
	buyLimitPriceBufferProduction = 0.002
	sellLimitPriceBufferSandbox   = 0.005
)

// BuyLimitPriceBuffer returns passive buy limit buffer for the account contour.
func BuyLimitPriceBuffer(accountKind *AccountKind) float64 {
	if accountKind != nil && *accountKind == AccountKindProduction {
		return buyLimitPriceBufferProduction
	}
	return buyLimitPriceBufferSandbox
}

// FormatBuyLimitBufferLabel renders buffer as a human label, e.g. "0.5%".
func FormatBuyLimitBufferLabel(buffer float64) string {
	return strconv.FormatFloat(buffer*100, 'g', -1, 64) + "%"
}

// SuggestedBuyLimitPricePct returns market + buffer as limit price %.
func SuggestedBuyLimitPricePct(basePct, buffer float64) shared.PriceUnitPct {
	return shared.PriceUnitPct(round4(basePct * (1 + buffer)))
}

// SellLimitPriceBuffer returns passive sell limit buffer.
func SellLimitPriceBuffer(accountKind *AccountKind) float64 {
	if accountKind != nil && *accountKind == AccountKindProduction {
		return buyLimitPriceBufferProduction
	}
	return sellLimitPriceBufferSandbox
}

// SuggestedSellLimitPricePct returns market - buffer as limit price %.
func SuggestedSellLimitPricePct(basePct, buffer float64) shared.PriceUnitPct {
	return shared.PriceUnitPct(round4(basePct * (1 - buffer)))
}

// ReferenceMarketPricePct picks broker price, bond last price, or fallback.
func ReferenceMarketPricePct(bondLastPrice, brokerCurrentPricePct *float64, fallback float64) float64 {
	if brokerCurrentPricePct != nil && *brokerCurrentPricePct > 0 {
		return *brokerCurrentPricePct
	}
	if bondLastPrice != nil && *bondLastPrice > 0 {
		return *bondLastPrice
	}
	return fallback
}

func round4(v float64) float64 {
	return float64(int(v*10000+0.5)) / 10000
}
