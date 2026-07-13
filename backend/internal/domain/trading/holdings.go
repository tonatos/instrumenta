package trading

import "time"

// HoldingView is a broker position enriched with market data.
type HoldingView struct {
	FIGI             string
	ISIN             string
	Name             string
	Lots             int
	Quantity         int
	LotSize          int
	CurrentPricePct  *float64
	CurrentNKDRub    *float64
	YTM              *float64
	MaturityDate     *time.Time
	OfferDate        *time.Time
	MarketValueRub   *float64
}
