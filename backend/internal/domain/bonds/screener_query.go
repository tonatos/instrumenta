package bonds

import (
	"sort"
	"strings"
	"time"
)

const (
	DefaultBondListPageSize = 50
	MaxBondListPageSize     = 100
	MaxBondListExportSize   = 5000
)

// BondListQuery describes screener filter/sort/pagination parameters.
type BondListQuery struct {
	FilterBy         string
	MaxDays          *int
	MinVolumeRub     *float64
	MinYTMNet        *float64
	MaxLotPriceRub   *float64
	CouponTypes      []string
	RiskLevels       []int
	HideDefault      bool
	HideSubordinated bool
	Search           string
	SortBy           string
	SortDesc         bool
	Page             int
	PageSize         int
	ExportAll        bool
}

// BondListResult is a paginated bond list.
type BondListResult struct {
	Bonds    []BondRecord
	Total    int
	Page     int
	PageSize int
	Source   string
}

// NormalizeBondListQuery fills defaults and caps page size.
func NormalizeBondListQuery(q BondListQuery) BondListQuery {
	if q.FilterBy == "" {
		q.FilterBy = "effective"
	}
	if q.Page < 1 {
		q.Page = 1
	}
	if q.PageSize <= 0 {
		q.PageSize = DefaultBondListPageSize
	}
	if q.ExportAll {
		q.PageSize = MaxBondListExportSize
		q.Page = 1
	} else if q.PageSize > MaxBondListPageSize {
		q.PageSize = MaxBondListPageSize
	}
	if q.SortBy == "" {
		q.SortBy = "score"
	}
	return q
}

// FilterBondList returns bonds matching query filters.
func FilterBondList(list []BondRecord, q BondListQuery) []BondRecord {
	q = NormalizeBondListQuery(q)
	search := strings.ToLower(strings.TrimSpace(q.Search))
	couponSet := stringSet(q.CouponTypes)
	riskSet := intSet(q.RiskLevels)

	var out []BondRecord
	for _, b := range list {
		if q.HideDefault && (b.HasDefault || b.HasTechnicalDefault) {
			continue
		}
		if q.HideSubordinated && b.SubordinatedFlag {
			continue
		}
		if q.MaxDays != nil {
			days := daysForFilter(b, q.FilterBy)
			if days == nil || *days > *q.MaxDays {
				continue
			}
		}
		if q.MinVolumeRub != nil && b.FilterVolumeRub() < *q.MinVolumeRub {
			continue
		}
		if q.MinYTMNet != nil && (b.YTMNet == nil || *b.YTMNet < *q.MinYTMNet) {
			continue
		}
		if q.MaxLotPriceRub != nil && *q.MaxLotPriceRub > 0 {
			if lot := b.PricePerLotRub(); lot != nil && *lot > *q.MaxLotPriceRub {
				continue
			}
		}
		if len(couponSet) > 0 && !couponSet[string(b.CouponType)] {
			continue
		}
		if len(riskSet) > 0 && !riskSet[int(b.RiskLevel)] {
			continue
		}
		if search != "" && !matchesSearch(b, search) {
			continue
		}
		out = append(out, b)
	}
	return out
}

func daysForFilter(b BondRecord, filterBy string) *int {
	if filterBy == "maturity" && b.MaturityDate != nil {
		days := int(time.Until(*b.MaturityDate).Hours() / 24)
		return &days
	}
	return b.DaysToMaturity
}

func matchesSearch(b BondRecord, q string) bool {
	return strings.Contains(strings.ToLower(b.Name), q) ||
		strings.Contains(strings.ToLower(b.Secid), q) ||
		strings.Contains(strings.ToLower(b.ISIN), q)
}

// SortBondList sorts bonds by a simple field (not score — use screening.SortBondsByResolvedScore).
func SortBondList(list []BondRecord, q BondListQuery) []BondRecord {
	q = NormalizeBondListQuery(q)
	if q.SortBy == "score" {
		return list
	}
	out := append([]BondRecord(nil), list...)
	desc := q.SortDesc
	sort.SliceStable(out, func(i, j int) bool {
		less := compareBondField(out[i], out[j], q.SortBy)
		if desc {
			return !less
		}
		return less
	})
	return out
}

func compareBondField(a, b BondRecord, field string) bool {
	switch field {
	case "ytm_net":
		return floatPtrLess(a.YTMNet, b.YTMNet)
	case "days_to_maturity":
		return intPtrLess(a.DaysToMaturity, b.DaysToMaturity)
	case "volume":
		return a.FilterVolumeRub() < b.FilterVolumeRub()
	case "name":
		return strings.ToLower(a.Name) < strings.ToLower(b.Name)
	case "last_price":
		return floatPtrLess(a.LastPrice, b.LastPrice)
	case "coupon_rate":
		return floatPtrLess(a.CouponRate, b.CouponRate)
	default:
		return strings.ToLower(a.Secid) < strings.ToLower(b.Secid)
	}
}

func floatPtrLess(a, b *float64) bool {
	av, bv := 0.0, 0.0
	if a != nil {
		av = *a
	}
	if b != nil {
		bv = *b
	}
	return av < bv
}

func intPtrLess(a, b *int) bool {
	av, bv := 0, 0
	if a != nil {
		av = *a
	}
	if b != nil {
		bv = *b
	}
	return av < bv
}

// PaginateBondList slices a list by page and returns total count.
func PaginateBondList(list []BondRecord, q BondListQuery) ([]BondRecord, int) {
	q = NormalizeBondListQuery(q)
	total := len(list)
	start := (q.Page - 1) * q.PageSize
	if start >= total {
		return nil, total
	}
	end := start + q.PageSize
	if end > total {
		end = total
	}
	return append([]BondRecord(nil), list[start:end]...), total
}

func stringSet(values []string) map[string]bool {
	if len(values) == 0 {
		return nil
	}
	out := make(map[string]bool, len(values))
	for _, v := range values {
		out[strings.ToLower(strings.TrimSpace(v))] = true
	}
	return out
}

func intSet(values []int) map[int]bool {
	if len(values) == 0 {
		return nil
	}
	out := make(map[int]bool, len(values))
	for _, v := range values {
		out[v] = true
	}
	return out
}
