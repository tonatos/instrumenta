package httpapi

import (
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/screening"
)

func (h *Handler) ListBonds(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	query := ParseBondListQuery(r)
	riskProfile := ParseRiskProfile(r.URL.Query().Get("risk_profile"))
	durationPolicy := ResolveDurationPolicy(r.URL.Query().Get("rate_scenario"))

	result, err := h.deps.Bonds.ListBonds(ctx, query, riskProfile, string(durationPolicy.RateScenario))
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	favoriteISINs, _ := h.deps.Favorites.ListISINs(ctx)
	favSet := make(map[string]bool, len(favoriteISINs))
	for _, isin := range favoriteISINs {
		favSet[isin] = true
	}
	screeningPolicy := screeningPolicyFromPortfolio(durationPolicy)
	scale := screening.DurationScaleYears(result.Bonds, screeningPolicy)
	bondsOut := make([]BondResponse, 0, len(result.Bonds))
	for i := range result.Bonds {
		b := result.Bonds[i]
		b.IsFavorite = favSet[b.ISIN]
		bondsOut = append(bondsOut, BondToResponse(b, riskProfile, durationPolicy, &scale))
	}
	WriteJSON(w, http.StatusOK, BondsListResponse{
		Bonds:    bondsOut,
		Source:   result.Source,
		Count:    len(bondsOut),
		Total:    result.Total,
		Page:     result.Page,
		PageSize: result.PageSize,
	})
}

func (h *Handler) BondsByISINs(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	isinList := splitCSV(r.URL.Query().Get("isins"))
	riskProfile := ParseRiskProfile(r.URL.Query().Get("risk_profile"))
	durationPolicy := ResolveDurationPolicy(r.URL.Query().Get("rate_scenario"))
	bondsLoaded, err := h.deps.Bonds.LoadByISINs(ctx, isinList, riskProfile, string(durationPolicy.RateScenario))
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	favoriteISINs, _ := h.deps.Favorites.ListISINs(ctx)
	favSet := make(map[string]bool, len(favoriteISINs))
	for _, isin := range favoriteISINs {
		favSet[isin] = true
	}
	screeningPolicy := screeningPolicyFromPortfolio(durationPolicy)
	scale := screening.DurationScaleYears(bondsLoaded, screeningPolicy)
	bondsOut := make([]BondResponse, 0, len(bondsLoaded))
	for i := range bondsLoaded {
		b := bondsLoaded[i]
		b.IsFavorite = favSet[b.ISIN]
		bondsOut = append(bondsOut, BondToResponse(b, riskProfile, durationPolicy, &scale))
	}
	WriteJSON(w, http.StatusOK, BondsListResponse{
		Bonds:  bondsOut,
		Source: "isins",
		Count:  len(bondsOut),
		Total:  len(bondsOut),
		Page:   1,
		PageSize: len(bondsOut),
	})
}

func (h *Handler) GetBond(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	secid := chi.URLParam(r, "secid")
	riskProfile := ParseRiskProfile(r.URL.Query().Get("risk_profile"))
	durationPolicy := ResolveDurationPolicy(r.URL.Query().Get("rate_scenario"))
	bond, err := h.deps.Bonds.LoadBySecid(ctx, secid, riskProfile, string(durationPolicy.RateScenario))
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if bond == nil && secid != "" {
		loaded, _ := h.deps.Bonds.LoadByISINs(ctx, []string{secid}, riskProfile, string(durationPolicy.RateScenario))
		if len(loaded) > 0 {
			bond = &loaded[0]
		}
	}
	if bond == nil {
		WriteNotFound(w, "Bond "+secid+" not found")
		return
	}
	favoriteISINs, _ := h.deps.Favorites.ListISINs(ctx)
	for _, isin := range favoriteISINs {
		if isin == bond.ISIN {
			bond.IsFavorite = true
			break
		}
	}
	universe, _ := h.deps.Bonds.LoadUniverse(ctx)
	screeningPolicy := screeningPolicyFromPortfolio(durationPolicy)
	scale := screening.DurationScaleYears(universe.Bonds, screeningPolicy)
	var coupons []map[string]any
	if bond.FIGI != "" {
		coupons, _ = h.deps.Bonds.GetCouponSchedule(ctx, bond.FIGI)
	}
	coupons = emptySlice(coupons)
	WriteJSON(w, http.StatusOK, map[string]any{
		"bond":    BondToResponse(*bond, riskProfile, durationPolicy, &scale),
		"coupons": coupons,
	})
}

func (h *Handler) RefreshBonds(w http.ResponseWriter, r *http.Request) {
	_ = h.deps.Bonds.InvalidateCaches(r.Context())
	WriteJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handler) RefreshRatings(w http.ResponseWriter, r *http.Request) {
	count, err := h.deps.Bonds.RefreshRatings(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, map[string]int{"count": count})
}

func (h *Handler) ListFavorites(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	isins, err := h.deps.Favorites.ListISINs(ctx)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	bondsLoaded, err := h.deps.Bonds.LoadByISINs(ctx, isins, portfolio.RiskProfileNormal, string(portfolio.RateScenarioHold))
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	bondsOut := make([]BondResponse, 0, len(bondsLoaded))
	for i := range bondsLoaded {
		bondsLoaded[i].IsFavorite = true
		bondsOut = append(bondsOut, BondToResponse(bondsLoaded[i], portfolio.RiskProfileNormal, portfolio.DefaultDurationPolicy, nil))
	}
	WriteJSON(w, http.StatusOK, BondsListResponse{
		Bonds:    bondsOut,
		Source:   "favorites",
		Count:    len(bondsOut),
		Total:    len(bondsOut),
		Page:     1,
		PageSize: len(bondsOut),
	})
}

func (h *Handler) AddFavorite(w http.ResponseWriter, r *http.Request) {
	isin := chi.URLParam(r, "isin")
	if err := h.deps.Favorites.Add(r.Context(), isin); err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, map[string]string{"isin": isin, "status": "added"})
}

func (h *Handler) RemoveFavorite(w http.ResponseWriter, r *http.Request) {
	isin := chi.URLParam(r, "isin")
	if err := h.deps.Favorites.Remove(r.Context(), isin); err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func splitCSV(value string) []string {
	parts := strings.Split(value, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
