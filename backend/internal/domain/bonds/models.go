package bonds

import (
	"fmt"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

type CouponType string

const (
	CouponTypeFixed    CouponType = "fixed"
	CouponTypeFloating CouponType = "floating"
	CouponTypeVariable CouponType = "variable"
	CouponTypeUnknown  CouponType = "unknown"
)

// CouponTypeLabels maps coupon types to Russian labels.
var CouponTypeLabels = map[CouponType]string{
	CouponTypeFixed:    "Фиксированный",
	CouponTypeFloating: "Плавающий",
	CouponTypeVariable: "Переменный",
	CouponTypeUnknown:  "Неизвестен",
}

type RiskLevel int

const (
	RiskLevelUnknown  RiskLevel = 0
	RiskLevelLow      RiskLevel = 1
	RiskLevelModerate RiskLevel = 2
	RiskLevelHigh     RiskLevel = 3
)

// RiskLevelLabels maps risk levels to Russian labels.
var RiskLevelLabels = map[RiskLevel]string{
	RiskLevelUnknown:  "Неизвестен",
	RiskLevelLow:      "Низкий",
	RiskLevelModerate: "Умеренный",
	RiskLevelHigh:     "Высокий",
}

// RatingOrder maps national rating scale to ordinal (higher = better).
var RatingOrder = map[string]int{
	"ruAAA": 12, "AAA": 12,
	"ruAA+": 11, "AA+": 11,
	"ruAA": 10, "AA": 10,
	"ruAA-": 9, "AA-": 9,
	"ruA+": 8, "A+": 8,
	"ruA": 7, "A": 7,
	"ruA-": 6, "A-": 6,
	"ruBBB+": 5, "BBB+": 5,
	"ruBBB": 4, "BBB": 4,
	"ruBBB-": 3, "BBB-": 3,
	"ruBB+": 2, "BB+": 2,
	"ruBB": 1, "BB": 1,
	"ruBB-": 0, "BB-": 0,
	"ruB+": -1, "B+": -1,
	"ruB": -2, "B": -2,
	"ruB-": -3, "B-": -3,
	"ruCCC": -4, "CCC": -4,
	"ruCC": -5, "CC": -5,
	"ruD": -6, "D": -6,
}

// BondRecord is a single bond in the screening universe.
type BondRecord struct {
	Secid string
	ISIN  string
	FIGI  string
	Name  string

	MaturityDate         *time.Time
	OfferDate            *time.Time
	OfferSubmissionStart *time.Time
	OfferSubmissionEnd   *time.Time
	OfferPricePct        *float64
	EffectiveDate        *time.Time
	DaysToMaturity       *int

	YTM    *float64
	YTMNet *float64

	CouponRate       *float64
	AccruedInterest  *float64
	CouponType       CouponType
	CouponPeriodDays *int
	NextCouponDate   *time.Time
	CouponValue      *float64

	LastPrice  *float64
	FaceValue  float64
	LotSize    int

	DurationDays *float64

	VolumeRub     *float64
	PrevVolumeRub *float64

	AmortizationFlag     bool
	FloatingCouponFlag   bool
	PerpetualFlag        bool
	SubordinatedFlag     bool
	ForQualInvestorFlag  bool
	LiquidityFlag        bool
	CallDate             *time.Time
	RiskLevel            RiskLevel

	HasDefault           bool
	HasTechnicalDefault  bool
	CreditRating         *string

	ProfileScores  map[string]float64
	Score          *float64
	YTMScore       *float64
	RiskScore      *float64
	LiquidityScore *float64

	IssuerName           string
	InstrumentFullName   string
	Sector               string
	Description          string
	AssetUID             string
	TInvestEnriched      bool
	APITradeAvailableFlag *bool

	IsFavorite bool
}

func (b BondRecord) FilterVolumeRub() float64 {
	if b.PrevVolumeRub != nil {
		return *b.PrevVolumeRub
	}
	if b.VolumeRub != nil {
		return *b.VolumeRub
	}
	return 0
}

func (b BondRecord) DurationYears() *float64 {
	if b.DurationDays != nil {
		v := *b.DurationDays / 365.0
		return &v
	}
	if b.DaysToMaturity != nil && *b.DaysToMaturity > 0 {
		v := float64(*b.DaysToMaturity) / 365.0
		return &v
	}
	return nil
}

func (b BondRecord) DurationIsProxy() bool {
	return b.DurationDays == nil && b.DaysToMaturity != nil && *b.DaysToMaturity > 0
}

func (b BondRecord) IsFloatingCoupon() bool {
	return b.FloatingCouponFlag || b.CouponType == CouponTypeFloating
}

// HasWarnings is true when structural risk flags are set.
func (b BondRecord) HasWarnings() bool {
	return b.AmortizationFlag ||
		b.FloatingCouponFlag ||
		b.SubordinatedFlag ||
		b.ForQualInvestorFlag ||
		b.CouponType == CouponTypeVariable ||
		b.CallDate != nil ||
		b.HasDefault ||
		b.HasTechnicalDefault
}

// WarningsList returns human-readable risk warnings.
func (b BondRecord) WarningsList(reference ...time.Time) []string {
	var warnings []string
	if b.HasDefault {
		warnings = append(warnings,
			"Эмитент в дефолте (MOEX HASDEFAULT): купоны/номинал не выплачены, "+
				"грейс-период истёк. Покупка крайне рискованна")
	}
	if b.HasTechnicalDefault {
		warnings = append(warnings,
			"Технический дефолт (MOEX HASTECHNICALDEFAULT): эмитент пропустил "+
				"выплату, но грейс-период ещё не истёк. Возможен переход в полный дефолт")
	}
	if b.AmortizationFlag {
		warnings = append(warnings,
			"Амортизация: номинал выплачивается частями — реальная доходность ниже купона")
	}
	if b.FloatingCouponFlag {
		warnings = append(warnings,
			"Плавающий купон: размер купона привязан к КС/RUONIA — доходность непредсказуема")
	}
	if b.CouponType == CouponTypeVariable {
		warnings = append(warnings, "Переменный купон: следующий купон неизвестен заранее")
	}
	if b.SubordinatedFlag {
		warnings = append(warnings, "Субординированная облигация: при банкротстве выплачивается последней")
	}
	if b.ForQualInvestorFlag {
		warnings = append(warnings, "Только для квалифицированных инвесторов")
	}
	if b.CallDate != nil {
		warnings = append(warnings,
			fmt.Sprintf("Колл-оферта %s: эмитент может досрочно выкупить облигацию",
				shared.FormatDate(b.CallDate, reference...)))
	}
	return warnings
}

func (b BondRecord) CleanPriceRub() *float64 {
	if b.LastPrice == nil {
		return nil
	}
	v := *b.LastPrice / 100.0 * b.FaceValue
	return &v
}

func (b BondRecord) DirtyPriceRub() *float64 {
	clean := b.CleanPriceRub()
	if clean == nil {
		return nil
	}
	aci := 0.0
	if b.AccruedInterest != nil {
		aci = *b.AccruedInterest
	}
	v := *clean + aci
	return &v
}

func (b BondRecord) PricePerLotRub() *float64 {
	dirty := b.DirtyPriceRub()
	if dirty == nil {
		return nil
	}
	v := *dirty * float64(b.LotSize)
	return &v
}

func Ptr[T any](v T) *T { return &v }

func BoolPtr(v bool) *bool { return &v }

func FloatPtr(v float64) *float64 { return &v }

func IntPtr(v int) *int { return &v }

func StrPtr(v string) *string { return &v }

func TimePtr(t time.Time) *time.Time { return &t }
