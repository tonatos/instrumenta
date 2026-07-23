package trading

import (
	"sort"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

const cashReconcileEpsilonRub = 0.01
const cashReconcileNoteThresholdRub = 1_000

var operationCashflowKinds = map[string]string{
	"OPERATION_TYPE_INPUT":               "deposit",
	"OPERATION_TYPE_OUTPUT":              "withdrawal",
	"OPERATION_TYPE_BUY":                 "purchase",
	"OPERATION_TYPE_BUY_CARD":            "purchase",
	"OPERATION_TYPE_BUY_MARGIN":          "purchase",
	"OPERATION_TYPE_SELL":                "sale",
	"OPERATION_TYPE_SELL_CARD":           "sale",
	"OPERATION_TYPE_SELL_MARGIN":         "sale",
	"OPERATION_TYPE_COUPON":              "coupon",
	"OPERATION_TYPE_BOND_REPAYMENT":      "maturity",
	"OPERATION_TYPE_BOND_REPAYMENT_FULL": "maturity",
	"OPERATION_TYPE_BROKER_FEE":          "fee",
	"OPERATION_TYPE_SERVICE_FEE":         "fee",
	"OPERATION_TYPE_OTHER_FEE":           "fee",
	"OPERATION_TYPE_TAX":                 "tax",
	"OPERATION_TYPE_TAX_PROGRESSIVE":     "tax",
	"OPERATION_TYPE_BOND_TAX":            "tax",
	"OPERATION_TYPE_BOND_TAX_PROGRESSIVE": "tax",
	"OPERATION_TYPE_TAX_CORRECTION":         "tax",
	"OPERATION_TYPE_TAX_CORRECTION_COUPON":  "tax",
}

// OperationsToCashflowEvents maps executed broker operations before today into plan journal lines.
func OperationsToCashflowEvents(ops []BrokerOperation, today time.Time) []portfolio.CashflowEvent {
	today = shared.DateOnly(today)
	var events []portfolio.CashflowEvent
	seq := 0
	for _, op := range ops {
		if op.State != "" && op.State != "OPERATION_STATE_EXECUTED" {
			continue
		}
		kind, ok := operationCashflowKinds[op.Type]
		if !ok || op.PaymentRub == nil {
			continue
		}
		date := shared.DateOnly(op.Date)
		if !date.Before(today) {
			continue
		}
		seq++
		amount := float64(*op.PaymentRub)
		label := OperationTypeLabel(op.Type)
		events = append(events, portfolio.CashflowEvent{
			Date: date, Kind: kind, AmountRub: amount,
			Description: label, IsProjected: false, JournalSeq: seq,
		})
	}
	sort.Slice(events, func(i, j int) bool {
		di, si := portfolio.JournalSortKey(events[i])
		dj, sj := portfolio.JournalSortKey(events[j])
		if di.Equal(dj) {
			return si < sj
		}
		return di.Before(dj)
	})
	return events
}

// ReconcileCashToBroker appends a reconciliation line on today so journal cash matches broker MoneyRub.
func ReconcileCashToBroker(events []portfolio.CashflowEvent, today time.Time, brokerMoneyRub float64) ([]portfolio.CashflowEvent, float64, bool) {
	today = shared.DateOnly(today)
	reconciled := portfolio.CashOnHandBeforeDate(events, today, 0)
	delta := brokerMoneyRub - reconciled
	if delta > -cashReconcileEpsilonRub && delta < cashReconcileEpsilonRub {
		return events, 0, false
	}
	out := append([]portfolio.CashflowEvent(nil), events...)
	seq := len(out) + 1
	out = append(out, portfolio.CashflowEvent{
		Date: today, Kind: "reconciliation", AmountRub: delta,
		Description: "Сверка с брокерским кэшем", IsProjected: false, JournalSeq: seq,
	})
	note := mathAbs(delta) > cashReconcileNoteThresholdRub
	return out, delta, note
}

func mathAbs(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}

// InvestedCapitalFromOperations returns net buy outflows from broker operations (positive rub).
func InvestedCapitalFromOperations(ops []BrokerOperation) float64 {
	total := 0.0
	for _, op := range ops {
		if op.State != "" && op.State != "OPERATION_STATE_EXECUTED" {
			continue
		}
		if !outflowTypes[op.Type] || op.PaymentRub == nil {
			continue
		}
		total += -float64(*op.PaymentRub)
	}
	return total
}
