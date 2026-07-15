package portfolio_test

import (
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

func TestInvestedCapitalFromPositionsCostBasisPlusCash(t *testing.T) {
	today := shared.MustParseDate("2026-07-15")
	positions := []portfolio.PortfolioPosition{
		{
			ISIN: "RU000A1", Lots: 10, LotSize: 1, FaceValue: 1000,
			PurchaseDate: today, PurchaseAmountRub: 99_000, Source: portfolio.PositionSourceAdopted,
		},
		{
			ISIN: "RU000A2", Lots: 5, LotSize: 1, FaceValue: 1000,
			PurchaseDate: today, PurchaseAmountRub: 48_500, Source: portfolio.PositionSourceAdopted,
		},
	}
	got := portfolio.InvestedCapitalFromPositions(positions, shared.Rub(3_447.4))
	want := 99_000 + 48_500 + 3_447.4
	if got < want-0.01 || got > want+0.01 {
		t.Fatalf("invested capital = %v, want %v", got, want)
	}
}

func TestInvestedCapitalFromPositionsEmptyHoldingsIsCashOnly(t *testing.T) {
	got := portfolio.InvestedCapitalFromPositions(nil, shared.Rub(632.14))
	if got != 632.14 {
		t.Fatalf("expected cash only, got %v", got)
	}
}

func TestInvestedCapitalTradingDoesNotDoubleCountMarketValue(t *testing.T) {
	// Regression: InvestedRub + UnrealizedValueRub + cash counted purchases and market twice.
	p := portfolio.Portfolio{
		Mode: portfolio.PortfolioModeTrading, CashBalanceRub: 2_136.42,
		Positions: []portfolio.PortfolioPosition{
			{
				ISIN: "RU000A1", Lots: 5, LotSize: 1, FaceValue: 1000,
				PurchaseDate: time.Date(2026, 7, 7, 0, 0, 0, 0, time.UTC),
				PurchaseAmountRub: 51_987, Source: portfolio.PositionSourceAdopted,
			},
		},
	}
	fromPositions := portfolio.InvestedCapitalFromPositions(p.Positions, shared.Rub(2_136.42))
	wrongDoubleCount := 122_573.29 + 249_045.3 + 2_136.42
	if fromPositions > wrongDoubleCount*0.8 {
		t.Fatalf("cost-basis invested %v should be well below double-count baseline %v", fromPositions, wrongDoubleCount)
	}
	if fromPositions < 51_987+2_136-1 || fromPositions > 51_987+2_136+1 {
		t.Fatalf("expected cost+cash, got %v", fromPositions)
	}
}
