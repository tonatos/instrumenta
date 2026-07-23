package portfolio_test

import (
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

func TestCashflowProjectedRowsFromTodaySkipsHistory(t *testing.T) {
	today := shared.MustParseDate("2026-07-15")
	events := []portfolio.CashflowEvent{
		{Date: shared.MustParseDate("2026-07-01"), Kind: "deposit", AmountRub: 20_000, JournalSeq: 1},
		{Date: shared.MustParseDate("2026-07-07"), Kind: "purchase", AmountRub: -5_000, JournalSeq: 2},
		{Date: shared.MustParseDate("2026-07-15"), Kind: "reconciliation", AmountRub: -100, JournalSeq: 3},
		{
			Date: shared.MustParseDate("2026-08-01"), Kind: "coupon", AmountRub: 200,
			IsProjected: true, JournalSeq: 4,
		},
	}
	rows := portfolio.CashflowProjectedRowsFromToday(events, 0, today)
	if len(rows) != 1 {
		t.Fatalf("expected 1 projected row, got %d", len(rows))
	}
	if rows[0].Kind != "coupon" {
		t.Fatalf("expected coupon, got %s", rows[0].Kind)
	}
	if rows[0].BalanceAfterRub != 15_200 {
		t.Fatalf("balance = %v, want 15200", rows[0].BalanceAfterRub)
	}
}

func TestCashflowRowsFromDateSkipsEarlierEvents(t *testing.T) {
	from := shared.MustParseDate("2026-07-10")
	events := []portfolio.CashflowEvent{
		{Date: shared.MustParseDate("2026-07-01"), Kind: "deposit", AmountRub: 20_000, JournalSeq: 1},
		{Date: shared.MustParseDate("2026-07-07"), Kind: "purchase", AmountRub: -5_000, JournalSeq: 2},
		{Date: shared.MustParseDate("2026-07-14"), Kind: "coupon", AmountRub: 200, JournalSeq: 3},
	}
	rows := portfolio.CashflowRowsFromDate(events, 0, from)
	if len(rows) != 1 {
		t.Fatalf("expected 1 row from date, got %d", len(rows))
	}
	if rows[0].Kind != "coupon" {
		t.Fatalf("expected coupon, got %s", rows[0].Kind)
	}
}

func TestCashflowRowsFromDateZeroShowsAll(t *testing.T) {
	events := []portfolio.CashflowEvent{
		{Date: time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC), Kind: "deposit", AmountRub: 100, JournalSeq: 1},
	}
	all := portfolio.CashflowRowsWithBalance(events, 0)
	filtered := portfolio.CashflowRowsFromDate(events, 0, time.Time{})
	if len(all) != len(filtered) {
		t.Fatalf("zero fromDate should match full journal")
	}
}
