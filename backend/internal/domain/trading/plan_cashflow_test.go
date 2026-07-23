package trading_test

import (
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

func rub(v float64) *shared.Rub {
	r := shared.Rub(v)
	return &r
}

func TestOperationsToCashflowEventsDepositBuyCoupon(t *testing.T) {
	today := shared.MustParseDate("2026-07-15")
	ops := []trading.BrokerOperation{
		{Type: "OPERATION_TYPE_INPUT", Date: shared.MustParseDate("2026-07-01"), PaymentRub: rub(20_000), State: "OPERATION_STATE_EXECUTED"},
		{Type: "OPERATION_TYPE_BUY", Date: shared.MustParseDate("2026-07-07"), PaymentRub: rub(-5_198.7), State: "OPERATION_STATE_EXECUTED"},
		{Type: "OPERATION_TYPE_COUPON", Date: shared.MustParseDate("2026-07-14"), PaymentRub: rub(115), State: "OPERATION_STATE_EXECUTED"},
	}
	events := trading.OperationsToCashflowEvents(ops, today)
	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d", len(events))
	}
	balance := portfolio.CashOnHandBeforeDate(events, today, 0)
	want := 20_000 - 5_198.7 + 115
	if balance < want-0.01 || balance > want+0.01 {
		t.Fatalf("balance before today = %v, want %v", balance, want)
	}
}

func TestReconcileCashToBrokerAddsDeltaOnToday(t *testing.T) {
	today := shared.MustParseDate("2026-07-15")
	events := []portfolio.CashflowEvent{
		{Date: shared.MustParseDate("2026-07-01"), Kind: "deposit", AmountRub: 10_000, JournalSeq: 1},
	}
	reconciled, delta, note := trading.ReconcileCashToBroker(events, today, 632.14)
	if len(reconciled) != 2 {
		t.Fatalf("expected deposit + reconciliation, got %d events", len(reconciled))
	}
	if reconciled[1].Kind != "reconciliation" {
		t.Fatalf("expected reconciliation kind, got %s", reconciled[1].Kind)
	}
	if !reconciled[1].Date.Equal(today) {
		t.Fatalf("reconciliation must be on today")
	}
	if reconciled[1].AmountRub < -9368.5 || reconciled[1].AmountRub > -9367.5 {
		t.Fatalf("reconciliation amount = %v", reconciled[1].AmountRub)
	}
	balance := portfolio.CashOnHandBeforeDate(reconciled, today.Add(24*time.Hour), 0)
	if balance < 632.13 || balance > 632.15 {
		t.Fatalf("balance after reconcile = %v, want 632.14", balance)
	}
	if delta < -9368.5 || delta > -9367.5 {
		t.Fatalf("delta = %v", delta)
	}
	if !note {
		t.Fatal("expected note for large reconciliation")
	}
}

func TestReconcileCashSkipsTinyDelta(t *testing.T) {
	today := shared.MustParseDate("2026-07-15")
	events := []portfolio.CashflowEvent{
		{Date: shared.MustParseDate("2026-07-14"), Kind: "deposit", AmountRub: 100, JournalSeq: 1},
	}
	reconciled, delta, note := trading.ReconcileCashToBroker(events, today, 100.005)
	if len(reconciled) != 1 {
		t.Fatalf("tiny delta should not add event, got %d", len(reconciled))
	}
	if delta != 0 || note {
		t.Fatalf("expected no delta/note, got delta=%v note=%v", delta, note)
	}
}
