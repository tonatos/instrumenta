package portfolio_test

import (
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

func TestCashflowRowsFromDateSkipsEarlierEvents(t *testing.T) {
	from := shared.MustParseDate("2026-07-10")
	events := []portfolio.CashflowEvent{
		{Date: shared.MustParseDate("2026-07-01"), Kind: "deposit", AmountRub: 20_000, JournalSeq: 1},
		{Date: shared.MustParseDate("2026-07-07"), Kind: "purchase", AmountRub: -5_000, JournalSeq: 2},
		{Date: shared.MustParseDate("2026-07-14"), Kind: "coupon", AmountRub: 200, JournalSeq: 3},
	}
	rows := portfolio.CashflowRowsFromDate(events, 0, from)
	if len(rows) != 1 {
		t.Fatalf("expected 1 row from attach date, got %d", len(rows))
	}
	if rows[0].Kind != "coupon" {
		t.Fatalf("expected coupon, got %s", rows[0].Kind)
	}
	if rows[0].BalanceAfterRub != 15_200 {
		t.Fatalf("balance = %v, want 15200", rows[0].BalanceAfterRub)
	}
}

func TestCashflowDisplayFromDateTradingUsesAttach(t *testing.T) {
	started := "2026-05-28T10:17:50+00:00"
	created := "2026-01-01T08:00:00+00:00"
	p := portfolio.Portfolio{
		Mode: portfolio.PortfolioModeTrading, CreatedAt: created, TradingStartedAt: &started,
	}
	got := portfolio.CashflowDisplayFromDate(p)
	want := shared.MustParseDate("2026-05-28")
	if !got.Equal(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestCashflowDisplayFromDateSimulationUsesCreated(t *testing.T) {
	p := portfolio.Portfolio{
		Mode: portfolio.PortfolioModeSimulation, CreatedAt: "2026-03-15T12:00:00Z",
	}
	got := portfolio.CashflowDisplayFromDate(p)
	want := shared.MustParseDate("2026-03-15")
	if !got.Equal(want) {
		t.Fatalf("got %v, want %v", got, want)
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
