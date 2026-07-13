package bonds

import "time"

// MOEXClient fetches bond market data from MOEX ISS.
type MOEXClient interface {
	FetchAllBondsUnfiltered() ([]BondRecord, error)
	FetchBondBySecid(secid string) (*BondRecord, error)
	FetchBondsByISINs(isins map[string]struct{}) ([]BondRecord, error)
	IsCacheFresh() bool
	InvalidateCache()
}

// RatingsLoader loads and applies credit ratings.
type RatingsLoader interface {
	LoadRatings() (map[string]any, error)
	LoadAutoRatings() (map[string]any, error)
	ApplyRatings(bonds []BondRecord, ratings map[string]any, autoRatings map[string]any) []BondRecord
}

// CouponPayment is one coupon from T-Invest schedule.
type CouponPayment struct {
	PaymentDate   *time.Time
	AmountRub     *float64
	CouponTypeRaw int
}

// Enricher adds T-Invest metadata to bonds.
type Enricher interface {
	EnrichBonds(bonds []BondRecord) []BondRecord
	EnrichBondDetail(bond *BondRecord)
	GetCouponSchedule(figi string) []CouponPayment
}
