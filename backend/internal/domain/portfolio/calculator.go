package portfolio

import (
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

type BondHoldResult struct {
	Secid            string
	Name             string
	Lots             int
	InvestedRub      float64
	CouponIncomeRub  float64
	RedemptionRub    float64
	ProfitRub        float64
	HoldDays         int
	YieldPct         *float64
}

type PortfolioHoldResult struct {
	Positions           []BondHoldResult
	TotalInvestedRub    float64
	TotalProfitRub      float64
	PortfolioYieldPct   *float64
}

func holdEndDate(b bonds.BondRecord, today time.Time) *time.Time {
	end := b.EffectiveDate
	if end == nil {
		end = b.MaturityDate
	}
	if end == nil || !end.After(today) {
		return nil
	}
	return end
}

func redemptionAmountGross(position PortfolioPosition, endDate time.Time) float64 {
	if position.OfferDate != nil && endDate.Equal(*position.OfferDate) {
		pricePct := 100.0
		if position.OfferPricePct != nil {
			pricePct = *position.OfferPricePct
		}
		return position.FaceValue * (pricePct / 100) * float64(position.BondsCount())
	}
	return position.FaceValue * float64(position.BondsCount())
}

func couponIncomeGross(position PortfolioPosition, endDate time.Time) float64 {
	payment := CouponPaymentPerEvent(position)
	if payment <= 0 {
		return 0
	}
	dates := CouponDatesInRange(position, endDate)
	return payment * float64(len(dates))
}

func CalculateBondHold(b bonds.BondRecord, lots int, today time.Time) *BondHoldResult {
	if lots < 1 {
		return nil
	}
	dirty := b.DirtyPriceRub()
	if dirty == nil || *dirty <= 0 {
		return nil
	}
	endDate := holdEndDate(b, today)
	if endDate == nil {
		return nil
	}
	position := PositionFromBond(b, lots, today, PositionSourceInitial)
	invested := position.PurchaseAmountRub
	couponIncome := couponIncomeGross(position, *endDate)
	redemption := redemptionAmountGross(position, *endDate)
	profit := couponIncome + redemption - invested
	holdDays := int(endDate.Sub(today).Hours() / 24)
	var yieldPct *float64
	if invested > 0 {
		v := round2(profit / invested * 100)
		yieldPct = &v
	}
	return &BondHoldResult{
		Secid: b.Secid, Name: b.Name, Lots: lots,
		InvestedRub: round2(invested), CouponIncomeRub: round2(couponIncome),
		RedemptionRub: round2(redemption), ProfitRub: round2(profit),
		HoldDays: holdDays, YieldPct: yieldPct,
	}
}

func CalculatePortfolioBudget(bs []bonds.BondRecord, budgetRub float64, today time.Time) PortfolioHoldResult {
	if len(bs) == 0 || budgetRub <= 0 {
		return PortfolioHoldResult{}
	}
	share := budgetRub / float64(len(bs))
	var positions []BondHoldResult
	var totalInvested, totalProfit float64
	for _, bond := range bs {
		dirty := bond.DirtyPriceRub()
		if dirty == nil || *dirty <= 0 {
			continue
		}
		lotCost := *dirty * float64(bond.LotSize)
		lots := maxInt(1, int(share/lotCost))
		hold := CalculateBondHold(bond, lots, today)
		if hold == nil {
			continue
		}
		positions = append(positions, *hold)
		totalInvested += hold.InvestedRub
		totalProfit += hold.ProfitRub
	}
	var portfolioYield *float64
	if totalInvested > 0 {
		v := round2(totalProfit / totalInvested * 100)
		portfolioYield = &v
	}
	return PortfolioHoldResult{
		Positions: positions, TotalInvestedRub: round2(totalInvested),
		TotalProfitRub: round2(totalProfit), PortfolioYieldPct: portfolioYield,
	}
}
