package trading

import (
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
)

// AccountKind is the T-Invest API contour (sandbox vs production).
type AccountKind = portfolio.AccountKind

const (
	AccountKindSandbox    = portfolio.AccountKindSandbox
	AccountKindProduction = portfolio.AccountKindProduction
)

// OrderDirection is broker order side.
type OrderDirection string

const (
	OrderDirectionBuy  OrderDirection = "BUY"
	OrderDirectionSell OrderDirection = "SELL"
)

// FrozenForecast is a scalar yield snapshot at trading-mode transition.
type FrozenForecast struct {
	ExpectedXIRRPct           *float64
	ExpectedTotalNetProfitRub float64
	ExpectedFinalValueRub     float64
	FrozenInitialAmountRub    float64
	HorizonDate               time.Time
	CreatedAt                 string
}
