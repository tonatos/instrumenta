package bonds

import (
	"context"
	"time"
)

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
	ApplyRatings(ctx context.Context, bonds []BondRecord) []BondRecord
	RefreshFromSmartLab(ctx context.Context) (int, error)
	MaybeRefreshStale(ctx context.Context)
}

// DefaultFlagsApplier sets HasDefault / HasTechnicalDefault on bonds.
type DefaultFlagsApplier interface {
	Apply(ctx context.Context, bonds []BondRecord) []BondRecord
	RefreshIfStale(ctx context.Context, bonds []BondRecord) error
	InvalidateCache()
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
