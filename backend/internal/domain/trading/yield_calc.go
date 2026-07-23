package trading

import (
	"math"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

var inflowTypes = map[string]bool{
	"OPERATION_TYPE_SELL":                true,
	"OPERATION_TYPE_COUPON":              true,
	"OPERATION_TYPE_BOND_REPAYMENT":      true,
	"OPERATION_TYPE_BOND_REPAYMENT_FULL": true,
}

var outflowTypes = map[string]bool{
	"OPERATION_TYPE_BUY":        true,
	"OPERATION_TYPE_BUY_CARD":   true,
	"OPERATION_TYPE_BUY_MARGIN": true,
}

var taxFeeTypes = map[string]bool{
	"OPERATION_TYPE_BOND_TAX":               true,
	"OPERATION_TYPE_BOND_TAX_PROGRESSIVE":   true,
	"OPERATION_TYPE_TAX":                    true,
	"OPERATION_TYPE_TAX_PROGRESSIVE":        true,
	"OPERATION_TYPE_TAX_CORRECTION":         true,
	"OPERATION_TYPE_TAX_CORRECTION_COUPON":  true,
	"OPERATION_TYPE_BROKER_FEE":             true,
	"OPERATION_TYPE_SERVICE_FEE":            true,
	"OPERATION_TYPE_OTHER_FEE":              true,
}

// ActualPerformance summarizes realized and unrealized portfolio returns.
type ActualPerformance struct {
	XIRRPct              *float64
	CouponsReceivedRub   shared.Rub
	TaxPaidRub           shared.Rub
	CommissionPaidRub    shared.Rub
	RealizedProfitRub    shared.Rub
	UnrealizedValueRub   shared.Rub
	InvestedRub          shared.Rub
	ReceivedRub          shared.Rub
	AsOf                 string
}

func filterPortfolioOperations(ops []BrokerOperation, figis map[string]bool) []BrokerOperation {
	var result []BrokerOperation
	for _, op := range ops {
		if op.FIGI != "" && figis[op.FIGI] {
			result = append(result, op)
		} else if op.FIGI == "" && taxFeeTypes[op.Type] {
			result = append(result, op)
		}
	}
	return result
}

func toXIRRCashflow(ops []BrokerOperation, asOf time.Time, currentValue shared.Rub) []struct {
	date   time.Time
	amount float64
} {
	var cashflow []struct {
		date   time.Time
		amount float64
	}
	for _, op := range ops {
		if op.PaymentRub == nil {
			continue
		}
		if inflowTypes[op.Type] || outflowTypes[op.Type] || taxFeeTypes[op.Type] {
			cashflow = append(cashflow, struct {
				date   time.Time
				amount float64
			}{op.Date, float64(*op.PaymentRub)})
		}
	}
	if currentValue > 0 {
		cashflow = append(cashflow, struct {
			date   time.Time
			amount float64
		}{asOf, float64(currentValue)})
	}
	return cashflow
}

// CalculatePortfolioXIRR returns annualized XIRR in percent or nil.
func CalculatePortfolioXIRR(ops []BrokerOperation, figis map[string]bool, currentValue shared.Rub, asOf time.Time) *float64 {
	portfolioOps := filterPortfolioOperations(ops, figis)
	if len(portfolioOps) == 0 {
		return nil
	}
	cashflow := toXIRRCashflow(portfolioOps, asOf, currentValue)
	if len(cashflow) < 2 {
		return nil
	}
	hasPos, hasNeg := false, false
	for _, cf := range cashflow {
		if cf.amount > 0 {
			hasPos = true
		}
		if cf.amount < 0 {
			hasNeg = true
		}
	}
	if !hasPos || !hasNeg {
		return nil
	}
	dates := make([]time.Time, len(cashflow))
	amounts := make([]float64, len(cashflow))
	for i, cf := range cashflow {
		dates[i] = shared.DateOnly(cf.date)
		amounts[i] = cf.amount
	}
	rate, ok := xirr(dates, amounts)
	if !ok {
		return nil
	}
	pct := rate * 100
	return &pct
}

func xirr(dates []time.Time, amounts []float64) (float64, bool) {
	if len(dates) != len(amounts) || len(dates) < 2 {
		return 0, false
	}
	base := shared.DateOnly(dates[0])
	yearFrac := func(d time.Time) float64 {
		return shared.DateOnly(d).Sub(base).Hours() / (365.0 * 24)
	}
	npv := func(rate float64) float64 {
		sum := 0.0
		for i, amt := range amounts {
			t := yearFrac(dates[i])
			sum += amt / math.Pow(1+rate, t)
		}
		return sum
	}
	rate := 0.1
	for i := 0; i < 100; i++ {
		f := npv(rate)
		deriv := 0.0
		for j, amt := range amounts {
			t := yearFrac(dates[j])
			deriv -= t * amt / math.Pow(1+rate, t+1)
		}
		if math.Abs(deriv) < 1e-12 {
			break
		}
		next := rate - f/deriv
		if math.Abs(next-rate) < 1e-7 {
			return next, true
		}
		rate = next
	}
	if math.IsNaN(rate) || math.IsInf(rate, 0) {
		return 0, false
	}
	return rate, true
}

func sumPayments(ops []BrokerOperation, types map[string]bool, figis map[string]bool) shared.Rub {
	total := 0.0
	for _, op := range ops {
		if !types[op.Type] {
			continue
		}
		if op.FIGI != "" && !figis[op.FIGI] {
			continue
		}
		if op.PaymentRub == nil {
			continue
		}
		total += float64(*op.PaymentRub)
	}
	return shared.Rub(total)
}

func estimateCurrentValue(p portfolio.Portfolio, snapshot BrokerSnapshot) shared.Rub {
	total := 0.0
	portfolioFigis := make(map[string]bool)
	for _, pos := range p.Positions {
		if pos.FIGI != nil {
			portfolioFigis[*pos.FIGI] = true
		}
	}
	for figi, brokerPos := range snapshot.BondPositions {
		if !portfolioFigis[figi] {
			continue
		}
		var position *portfolio.PortfolioPosition
		for i := range p.Positions {
			if p.Positions[i].FIGI != nil && *p.Positions[i].FIGI == figi {
				position = &p.Positions[i]
				break
			}
		}
		if position == nil {
			continue
		}
		var cleanPerBond float64
		if brokerPos.CurrentPricePct == nil {
			cleanPerBond = position.FaceValue
		} else {
			cleanPerBond = float64(*brokerPos.CurrentPricePct) / 100 * position.FaceValue
		}
		nkd := 0.0
		if brokerPos.CurrentNKDRub != nil {
			nkd = float64(*brokerPos.CurrentNKDRub)
		}
		total += (cleanPerBond + nkd) * float64(brokerPos.Quantity)
	}
	return shared.Rub(total)
}

// SummarizeActualPerformance builds the UI performance card.
func SummarizeActualPerformance(
	p portfolio.Portfolio,
	snapshot BrokerSnapshot,
	operations []BrokerOperation,
	asOf time.Time,
) ActualPerformance {
	figis := make(map[string]bool)
	for _, pos := range p.Positions {
		if pos.FIGI != nil {
			figis[*pos.FIGI] = true
		}
	}
	if len(figis) == 0 {
		return ActualPerformance{AsOf: asOf.UTC().Format(time.RFC3339)}
	}
	coupons := sumPayments(operations, map[string]bool{"OPERATION_TYPE_COUPON": true}, figis)
	taxTypes := map[string]bool{
		"OPERATION_TYPE_BOND_TAX": true, "OPERATION_TYPE_BOND_TAX_PROGRESSIVE": true,
		"OPERATION_TYPE_TAX": true, "OPERATION_TYPE_TAX_PROGRESSIVE": true,
		"OPERATION_TYPE_TAX_CORRECTION": true, "OPERATION_TYPE_TAX_CORRECTION_COUPON": true,
	}
	taxPaid := shared.Rub(-float64(sumPayments(operations, taxTypes, figis)))
	commissionTypes := map[string]bool{
		"OPERATION_TYPE_BROKER_FEE": true, "OPERATION_TYPE_SERVICE_FEE": true, "OPERATION_TYPE_OTHER_FEE": true,
	}
	commission := shared.Rub(-float64(sumPayments(operations, commissionTypes, figis)))
	invested := shared.Rub(-float64(sumPayments(operations, outflowTypes, figis)))
	received := sumPayments(operations, inflowTypes, figis)
	currentValue := estimateCurrentValue(p, snapshot)
	realized := shared.Rub(float64(received) - float64(invested))
	xirr := CalculatePortfolioXIRR(operations, figis, currentValue, asOf)
	return ActualPerformance{
		XIRRPct:            xirr,
		CouponsReceivedRub: coupons,
		TaxPaidRub:         taxPaid,
		CommissionPaidRub:  commission,
		RealizedProfitRub:  realized,
		UnrealizedValueRub: currentValue,
		InvestedRub:        invested,
		ReceivedRub:        received,
		AsOf:               asOf.UTC().Format(time.RFC3339),
	}
}
