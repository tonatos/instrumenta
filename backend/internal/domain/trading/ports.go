package trading

import (
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

// BrokerBondPosition is a bond lot on the broker account.
type BrokerBondPosition struct {
	FIGI             string
	InstrumentUID    string
	Ticker           string
	Quantity         int
	Lots             int
	Blocked          int
	CurrentPricePct  *shared.PriceUnitPct
	CurrentNKDRub    *shared.Rub
	AveragePricePct  *shared.PriceUnitPct
}

// BrokerOtherInstrument is a non-bond instrument on the account.
type BrokerOtherInstrument struct {
	InstrumentType string
	FIGI           string
	Ticker         string
	Quantity       int
}

// BrokerSnapshot is a point-in-time broker account state.
type BrokerSnapshot struct {
	AccountID         string
	AccountKind       AccountKind
	MoneyRub          shared.Rub
	BondPositions     map[string]BrokerBondPosition
	OtherInstruments  []BrokerOtherInstrument
	FetchedAt         string
	BlockedMoneyRub   shared.Rub
}

func (s BrokerSnapshot) HasForeignInstruments() bool {
	return len(s.OtherInstruments) > 0
}

func (s BrokerSnapshot) AvailableMoneyRub() shared.Rub {
	v := float64(s.MoneyRub) - float64(s.BlockedMoneyRub)
	if v < 0 {
		v = 0
	}
	return shared.Rub(v)
}

// BrokerOperation is a historical account operation.
type BrokerOperation struct {
	ID             string
	Type           string
	State          string
	Date           time.Time
	FIGI           string
	InstrumentUID  string
	InstrumentType string
	PaymentRub     *shared.Rub
	Quantity       int
	PricePct       *shared.PriceUnitPct
	CommissionRub  *shared.Rub
}

// BrokerActiveOrder is a live broker order (NEW / PARTIALLYFILL).
type BrokerActiveOrder struct {
	OrderID               string
	RequestUID            string
	FIGI                  string
	Direction             string
	LotsRequested         int
	LotsExecuted          int
	Status                string
	PricePct              *float64
	TotalOrderAmountRub   *float64
	InitialCommissionRub  *float64
}
