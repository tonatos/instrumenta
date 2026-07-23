package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/tonatos/bond-monitor/backend/internal/domain/preferences"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

type PutPreferencesRequest struct {
	TaxRate *float64 `json:"tax_rate"`
}

type PreferencesResponse struct {
	TaxRate float64 `json:"tax_rate"`
}

func (h *Handler) GetPreferences(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok || user == nil {
		WriteUnauthorized(w, "")
		return
	}
	taxPct := preferences.DefaultTaxRatePct
	if h.deps.Users != nil {
		if pct, err := h.deps.Users.TaxRatePct(r.Context(), user.TelegramID); err == nil {
			taxPct = pct
		}
	}
	WriteJSON(w, http.StatusOK, PreferencesResponse{TaxRate: taxPct})
}

func (h *Handler) PutPreferences(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok || user == nil {
		WriteUnauthorized(w, "")
		return
	}
	if h.deps.Users == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "users store unavailable")
		return
	}
	var req PutPreferencesRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		WriteClientError(w, http.StatusBadRequest, "invalid json")
		return
	}
	if req.TaxRate == nil {
		WriteClientError(w, http.StatusBadRequest, "tax_rate is required")
		return
	}
	if err := h.deps.Users.SetTaxRatePct(r.Context(), user.TelegramID, *req.TaxRate); err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	normalized, _ := preferences.NormalizeTaxRatePct(*req.TaxRate)
	WriteJSON(w, http.StatusOK, PreferencesResponse{TaxRate: normalized})
}
