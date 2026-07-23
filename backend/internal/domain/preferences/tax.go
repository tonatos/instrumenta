package preferences

import "fmt"

// Allowed personal income tax rates (НДФЛ), percent points.
// 0 = ignore tax (gross figures).
var AllowedTaxRatePct = []float64{0, 13, 15, 18, 20, 22}

const DefaultTaxRatePct float64 = 13

// NormalizeTaxRatePct returns pct if allowed, otherwise an error.
func NormalizeTaxRatePct(pct float64) (float64, error) {
	for _, allowed := range AllowedTaxRatePct {
		if pct == allowed {
			return allowed, nil
		}
	}
	return 0, fmt.Errorf("tax_rate must be one of 0, 13, 15, 18, 20, 22")
}

// TaxRateFraction converts percent points to a 0–1 fraction.
func TaxRateFraction(pct float64) float64 {
	return pct / 100.0
}
