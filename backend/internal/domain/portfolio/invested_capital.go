package portfolio

import "github.com/tonatos/bond-monitor/backend/internal/domain/shared"

func InvestedCapitalRub(p Portfolio, accountMoneyRub *float64) float64 {
	if accountMoneyRub != nil {
		deployed := 0.0
		for _, position := range OpenPositions(p.Positions) {
			deployed += PositionCostBasis(position)
		}
		return round2(deployed + *accountMoneyRub)
	}
	if p.IsTrading() {
		deployed := 0.0
		for _, position := range OpenPositions(p.Positions) {
			deployed += PositionCostBasis(position)
		}
		return round2(deployed + p.CashBalanceRub)
	}
	return round2(p.InitialAmountRub)
}

func InvestedCapitalFromSnapshot(p Portfolio, moneyRub shared.Rub) float64 {
	v := float64(moneyRub)
	return InvestedCapitalRub(p, &v)
}

// InvestedCapitalFromPositions sums open position cost basis plus broker cash.
func InvestedCapitalFromPositions(positions []PortfolioPosition, moneyRub shared.Rub) float64 {
	deployed := 0.0
	for _, position := range OpenPositions(positions) {
		deployed += PositionCostBasis(position)
	}
	return round2(deployed + float64(moneyRub))
}
