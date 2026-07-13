package portfolio

import (
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

const (
	buyLimitBufferSandbox    = 0.005
	buyLimitBufferProduction = 0.002
	sellLimitBufferSandbox   = 0.005
)

func BuyLimitPriceBuffer(accountKind *AccountKind) float64 {
	if accountKind != nil && *accountKind == AccountKindProduction {
		return buyLimitBufferProduction
	}
	return buyLimitBufferSandbox
}

func SuggestedBuyLimitPricePct(basePct, buffer float64) shared.PriceUnitPct {
	return shared.PriceUnitPct(round4(basePct * (1 + buffer)))
}

func round4(v float64) float64 {
	return float64(int(v*10000+0.5)) / 10000
}

func SellLimitPriceBuffer(accountKind *AccountKind) float64 {
	if accountKind != nil && *accountKind == AccountKindProduction {
		return buyLimitBufferProduction
	}
	return sellLimitBufferSandbox
}

func SuggestedSellLimitPricePct(basePct, buffer float64) shared.PriceUnitPct {
	return shared.PriceUnitPct(round4(basePct * (1 - buffer)))
}

func ReferenceMarketPricePct(bondLastPrice, brokerCurrentPricePct *float64, fallback float64) float64 {
	if brokerCurrentPricePct != nil && *brokerCurrentPricePct > 0 {
		return *brokerCurrentPricePct
	}
	if bondLastPrice != nil && *bondLastPrice > 0 {
		return *bondLastPrice
	}
	return fallback
}

func PositionCostBasis(position PortfolioPosition) float64 {
	if position.PurchaseAmountRub > 0 {
		return position.PurchaseAmountRub
	}
	return position.PurchaseDirtyPriceRub * float64(position.Lots*position.LotSize)
}
