// Package shared provides strict monetary/quantity types for the trading domain.
package shared

import (
	"math"
)

// Rub is an amount in Russian rubles (including kopecks).
type Rub float64

// PriceUnitPct is a bond price as percent of face value (100.0 = par).
type PriceUnitPct float64

// Lots is the number of exchange lots.
type Lots int

// MaxOrderAmountRub is the T-Invest API hard limit per order.
const MaxOrderAmountRub Rub = 30_000_000

// Quotation mirrors proto Quotation (units + nano fixed-point).
type Quotation struct {
	Units int64
	Nano  int64
}

// MoneyValue is the duck-typed proto MoneyValue interface.
type MoneyValue interface {
	Currency() string
	Units() int64
	Nano() int64
}

// QuotationReader is the duck-typed proto Quotation interface.
type QuotationReader interface {
	Units() int64
	Nano() int64
}

// LotCostRub returns dirty price of one lot in rubles.
func LotCostRub(pricePct PriceUnitPct, faceValue float64, lotSize int, aciRub float64) Rub {
	cleanPerBond := float64(pricePct) / 100.0 * faceValue
	dirtyPerBond := cleanPerBond + aciRub
	return Rub(dirtyPerBond * float64(lotSize))
}

// OrderAmountRub returns total order cost (lots × lot dirty price).
func OrderAmountRub(pricePct PriceUnitPct, faceValue float64, lotSize int, lots Lots, aciRub float64) Rub {
	return Rub(float64(LotCostRub(pricePct, faceValue, lotSize, aciRub)) * float64(lots))
}

// PctToQuotation converts a numeric value to Quotation (9 decimal places, half-up).
func PctToQuotation(pricePct PriceUnitPct) Quotation {
	quantized := roundHalfUp9(float64(pricePct))
	units := int64(quantized)
	frac := quantized - float64(units)
	nano := int64(math.Round(frac * 1_000_000_000))
	if nano == 1_000_000_000 {
		units++
		nano = 0
	}
	return Quotation{Units: units, Nano: nano}
}

// BondCleanPricePctFromRub converts clean ruble price per bond to % of face value.
func BondCleanPricePctFromRub(cleanPriceRub, faceValue float64) PriceUnitPct {
	if faceValue <= 0 {
		panic("face_value must be positive")
	}
	return PriceUnitPct(cleanPriceRub / faceValue * 100.0)
}

// BondCleanPriceQuotation converts % of face to ruble clean price Quotation per bond.
func BondCleanPriceQuotation(pricePct PriceUnitPct, faceValue float64) Quotation {
	cleanPerBond := float64(pricePct) / 100.0 * faceValue
	return PctToQuotation(PriceUnitPct(cleanPerBond))
}

// QuotationToPct converts Quotation back to a float percent/price value.
func QuotationToPct(q Quotation) PriceUnitPct {
	return PriceUnitPct(float64(q.Units) + float64(q.Nano)/1_000_000_000.0)
}

// MoneyValueToRub converts proto MoneyValue to Rub (nil for non-RUB or nil input).
func MoneyValueToRub(mv MoneyValue) *Rub {
	if mv == nil {
		return nil
	}
	currency := mv.Currency()
	if currency != "" && currency != "rub" {
		return nil
	}
	v := Rub(float64(mv.Units()) + float64(mv.Nano())/1_000_000_000.0)
	return &v
}

// QuotationToFloat converts proto Quotation to float (nil for zero/empty).
func QuotationToFloat(q QuotationReader) *float64 {
	if q == nil {
		return nil
	}
	units := q.Units()
	nano := q.Nano()
	if units == 0 && nano == 0 {
		return nil
	}
	v := float64(units) + float64(nano)/1_000_000_000.0
	return &v
}

func roundHalfUp9(v float64) float64 {
	return math.Round(v*1_000_000_000) / 1_000_000_000
}
