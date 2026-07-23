package httpapi

import (
	"net/http"
	"strconv"
	"strings"

	domainBonds "github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

func ParseBondListQuery(r *http.Request) domainBonds.BondListQuery {
	q := r.URL.Query()
	query := domainBonds.BondListQuery{
		FilterBy:         q.Get("filter_by"),
		Search:           q.Get("q"),
		SortBy:           q.Get("sort_by"),
		SortDesc:         parseBool(q.Get("sort_desc")),
		HideDefault:      parseBool(q.Get("hide_default")),
		HideSubordinated: parseBool(q.Get("hide_subordinated")),
		ExportAll:        parseBool(q.Get("export")),
	}
	if v := strings.TrimSpace(q.Get("max_days")); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			query.MaxDays = &n
		}
	}
	if v := strings.TrimSpace(q.Get("min_volume_rub")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			query.MinVolumeRub = &f
		}
	}
	if v := strings.TrimSpace(q.Get("min_ytm_net")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			query.MinYTMNet = &f
		}
	}
	if v := strings.TrimSpace(q.Get("max_lot_price_rub")); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			query.MaxLotPriceRub = &f
		}
	}
	if v := strings.TrimSpace(q.Get("coupon_types")); v != "" {
		query.CouponTypes = splitCSV(v)
	}
	if v := strings.TrimSpace(q.Get("risk_levels")); v != "" {
		for _, part := range splitCSV(v) {
			if n, err := strconv.Atoi(part); err == nil {
				query.RiskLevels = append(query.RiskLevels, n)
			}
		}
	}
	if v := strings.TrimSpace(q.Get("sectors")); v != "" {
		query.Sectors = splitCSV(v)
	}
	if v := strings.TrimSpace(q.Get("page")); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			query.Page = n
		}
	}
	if v := strings.TrimSpace(q.Get("page_size")); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			query.PageSize = n
		}
	}
	if query.SortBy == "score" && q.Get("sort_desc") == "" {
		query.SortDesc = true
	}
	return domainBonds.NormalizeBondListQuery(query)
}

func parseBool(value string) bool {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}
