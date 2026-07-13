package portfolio

// PriceGainTotal is positive (face - clean purchase) × bonds count.
func PriceGainTotal(position PortfolioPosition) float64 {
	cleanAtPurchase := position.PurchaseCleanPricePct / 100 * position.FaceValue
	diff := position.FaceValue - cleanAtPurchase
	return diff * float64(position.BondsCount())
}

// NetRedemptionAmount returns maturity/put proceeds after income tax on price gain.
func NetRedemptionAmount(position PortfolioPosition, taxRate float64, isPut bool) float64 {
	var redemptionPerBond float64
	if isPut {
		pricePct := 100.0
		if position.OfferPricePct != nil {
			pricePct = *position.OfferPricePct
		}
		redemptionPerBond = position.FaceValue * (pricePct / 100)
	} else {
		redemptionPerBond = position.FaceValue
	}
	gross := redemptionPerBond * float64(position.BondsCount())
	cleanAtPurchase := position.PurchaseCleanPricePct / 100 * position.FaceValue
	taxableGain := max(0, (redemptionPerBond-cleanAtPurchase)*float64(position.BondsCount()))
	return gross - taxableGain*taxRate
}

func max(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
