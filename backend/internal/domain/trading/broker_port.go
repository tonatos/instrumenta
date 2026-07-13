package trading

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

// AccountInfo is a broker account summary for UI selectors.
type AccountInfo struct {
	ID          string
	Name        string
	Kind        AccountKind
	AccessLevel string
	Status      string
	IsWritable  bool
}

// InfraBondPosition is a bond lot on the broker account (infrastructure DTO).
type InfraBondPosition struct {
	FIGI            string
	InstrumentUID   string
	Ticker          string
	Quantity        int
	Lots            int
	Blocked         int
	CurrentPricePct *shared.PriceUnitPct
	CurrentNKDRub   *shared.Rub
	AveragePricePct *shared.PriceUnitPct
}

// InfraOtherInstrument is a non-bond instrument on the account.
type InfraOtherInstrument struct {
	InstrumentType string
	FIGI           string
	Ticker         string
	Quantity       int
}

// InfraAccountSnapshot is a point-in-time broker account state.
type InfraAccountSnapshot struct {
	AccountID        string
	AccountKind      AccountKind
	MoneyRub         shared.Rub
	BlockedMoneyRub  shared.Rub
	BondPositions    map[string]InfraBondPosition
	OtherInstruments []InfraOtherInstrument
	FetchedAt        string
}

func (s InfraAccountSnapshot) AvailableMoneyRub() shared.Rub {
	v := float64(s.MoneyRub) - float64(s.BlockedMoneyRub)
	if v < 0 {
		v = 0
	}
	return shared.Rub(v)
}

// InfraOperationRecord is a historical account operation.
type InfraOperationRecord struct {
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

// InfraOrderState is a live broker order.
type InfraOrderState struct {
	OrderID               string
	RequestUID            string
	FIGI                  string
	Direction             OrderDirection
	LotsRequested         int
	LotsExecuted          int
	ExecutionReportStatus string
	PricePct              *shared.PriceUnitPct
	TotalOrderAmountRub   *shared.Rub
	InitialCommissionRub  *shared.Rub
	OrderDate             *time.Time
}

// InfraPostOrderResult is the response from placing an order.
type InfraPostOrderResult struct {
	OrderID               string
	RequestUID            string
	ExecutionReportStatus string
	LotsExecuted          int
	LotsRequested         int
	TotalOrderAmountRub   *shared.Rub
	InitialCommissionRub  *shared.Rub
}

// InfraOrderPricePreview is a broker order cost preview.
type InfraOrderPricePreview struct {
	LotsRequested       int
	CleanAmountRub      *shared.Rub
	AciAmountRub        *shared.Rub
	TotalOrderAmountRub *shared.Rub
	ExecutedCommission  *shared.Rub
}

// TradeInstrument resolves FIGI/UID for order placement.
type TradeInstrument struct {
	FIGI          string
	InstrumentUID string
	LotSize       int
}

// BrokerClient is the port for T-Invest broker I/O.
type BrokerClient interface {
	ListAccounts(kind AccountKind) ([]AccountInfo, error)
	GetAccountSnapshot(kind AccountKind, accountID string) (InfraAccountSnapshot, error)
	GetAccountOperations(kind AccountKind, accountID string, fromDate time.Time) ([]InfraOperationRecord, error)
	GetActiveOrders(kind AccountKind, accountID string) ([]InfraOrderState, error)
	GetOrderState(kind AccountKind, accountID, orderID string) (InfraOrderState, error)
	ResolveFIGIForISIN(isin string) (string, error)
	CheckTradeAvailable(figi, instrumentUID string) (*TradeInstrument, error)
	EnsureOrderInstrument(figi, instrumentUID, isin string, direction OrderDirection) (TradeInstrument, error)
	GetLastPricePct(figi string) (*float64, error)
	PreviewOrderPrice(kind AccountKind, accountID, figi, instrumentUID string, direction OrderDirection, lots shared.Lots, pricePct shared.PriceUnitPct) (InfraOrderPricePreview, error)
	PostLimitOrder(kind AccountKind, accountID, figi, instrumentUID string, direction OrderDirection, lots shared.Lots, pricePct shared.PriceUnitPct, requestUID string) (InfraPostOrderResult, error)
	PostMarketSellOrder(kind AccountKind, accountID, figi, instrumentUID string, lots shared.Lots, requestUID string, referencePricePct *shared.PriceUnitPct, lotSize int) (InfraPostOrderResult, error)
	CancelOrder(kind AccountKind, accountID, orderID string) error
	OpenSandboxAccount(name string) (string, error)
	CloseSandboxAccount(accountID string) error
	SandboxPayIn(accountID string, amount shared.Rub) (shared.Rub, error)
	MakeRequestUID(accountID, figi, direction string, lots int, orderKey, salt string) string
}
