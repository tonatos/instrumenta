package tinvest

import (
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

// ToBrokerSnapshot maps infrastructure snapshot to domain port type.
func ToBrokerSnapshot(s trading.InfraAccountSnapshot) trading.BrokerSnapshot {
	positions := make(map[string]trading.BrokerBondPosition, len(s.BondPositions))
	for figi, pos := range s.BondPositions {
		positions[figi] = trading.BrokerBondPosition{
			FIGI: pos.FIGI, InstrumentUID: pos.InstrumentUID, Ticker: pos.Ticker,
			Quantity: pos.Quantity, Lots: pos.Lots, Blocked: pos.Blocked,
			CurrentPricePct: pos.CurrentPricePct, CurrentNKDRub: pos.CurrentNKDRub,
			AveragePricePct: pos.AveragePricePct,
		}
	}
	others := make([]trading.BrokerOtherInstrument, 0, len(s.OtherInstruments))
	for _, ins := range s.OtherInstruments {
		others = append(others, trading.BrokerOtherInstrument{
			InstrumentType: ins.InstrumentType, FIGI: ins.FIGI, Ticker: ins.Ticker, Quantity: ins.Quantity,
		})
	}
	return trading.BrokerSnapshot{
		AccountID: s.AccountID, AccountKind: s.AccountKind,
		MoneyRub: s.MoneyRub, BlockedMoneyRub: s.BlockedMoneyRub,
		BondPositions: positions, OtherInstruments: others, FetchedAt: s.FetchedAt,
	}
}

// ToBrokerOperations maps infrastructure operations to domain port type.
func ToBrokerOperations(ops []trading.InfraOperationRecord) []trading.BrokerOperation {
	result := make([]trading.BrokerOperation, 0, len(ops))
	for _, op := range ops {
		result = append(result, trading.BrokerOperation{
			ID: op.ID, Type: op.Type, State: op.State, Date: op.Date,
			FIGI: op.FIGI, InstrumentUID: op.InstrumentUID, InstrumentType: op.InstrumentType,
			PaymentRub: op.PaymentRub, Quantity: op.Quantity, PricePct: op.PricePct, CommissionRub: op.CommissionRub,
		})
	}
	return result
}

// ToBrokerActiveOrders maps infrastructure orders to domain port type.
func ToBrokerActiveOrders(orders []trading.InfraOrderState) []trading.BrokerActiveOrder {
	result := make([]trading.BrokerActiveOrder, 0, len(orders))
	for _, o := range orders {
		var pricePct *float64
		if o.PricePct != nil {
			v := float64(*o.PricePct)
			pricePct = &v
		}
		var total, commission *float64
		if o.TotalOrderAmountRub != nil {
			v := float64(*o.TotalOrderAmountRub)
			total = &v
		}
		if o.InitialCommissionRub != nil {
			v := float64(*o.InitialCommissionRub)
			commission = &v
		}
		result = append(result, trading.BrokerActiveOrder{
			OrderID: o.OrderID, RequestUID: o.RequestUID, FIGI: o.FIGI,
			Direction: string(o.Direction), LotsRequested: o.LotsRequested, LotsExecuted: o.LotsExecuted,
			Status: o.ExecutionReportStatus, PricePct: pricePct,
			TotalOrderAmountRub: total, InitialCommissionRub: commission,
		})
	}
	return result
}

// RubPtr is a helper for optional rub amounts.
func RubPtr(v float64) *shared.Rub {
	r := shared.Rub(v)
	return &r
}
