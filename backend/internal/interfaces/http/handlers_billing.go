package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	appbilling "github.com/tonatos/bond-monitor/backend/internal/application/billing"
	"github.com/tonatos/bond-monitor/backend/internal/domain/billing"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

func (h *Handler) requireFeature(w http.ResponseWriter, r *http.Request, feature billing.Feature) bool {
	if h.deps.Billing == nil {
		return true
	}
	owner, _ := auth.OwnerTelegramID(r.Context())
	if owner == 0 {
		WriteUnauthorized(w, "")
		return false
	}
	if err := h.deps.Billing.RequireFeature(r.Context(), owner, feature); err != nil {
		_ = WriteAppError(w, err)
		return false
	}
	return true
}

func (h *Handler) requireTradingPortfolioAccess(w http.ResponseWriter, r *http.Request, p *portfolio.Portfolio) bool {
	if p == nil || !p.IsTrading() {
		return true
	}
	return h.requireFeature(w, r, billing.FeatureTradingPortfolioAccess)
}

// gateTradingPortfolioID blocks trading-mode portfolios without subscription (402).
// Missing portfolios return true so the handler can emit 404.
func (h *Handler) gateTradingPortfolioID(w http.ResponseWriter, r *http.Request, portfolioID string) bool {
	if h.deps.Portfolios == nil {
		return true
	}
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), portfolioID)
	if err != nil || p == nil {
		return true
	}
	return h.requireTradingPortfolioAccess(w, r, p)
}

func (h *Handler) accessLockedForOwner(r *http.Request, owner int64, p portfolio.Portfolio) bool {
	if !p.IsTrading() || h.deps.Billing == nil {
		return false
	}
	ok, err := h.deps.Billing.HasFeature(r.Context(), owner, billing.FeatureTradingPortfolioAccess)
	if err != nil {
		return false
	}
	return !ok
}

func (h *Handler) GetBillingCatalog(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	catalog, err := h.deps.Billing.GetCatalog(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, catalog)
}

func (h *Handler) GetBillingStatus(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	owner, _ := auth.OwnerTelegramID(r.Context())
	status, err := h.deps.Billing.GetStatus(r.Context(), owner)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, status)
}

func (h *Handler) GetBillingLedger(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	owner, _ := auth.OwnerTelegramID(r.Context())
	limit := 50
	if raw := r.URL.Query().Get("limit"); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n > 0 {
			limit = n
		}
	}
	entries, err := h.deps.Billing.ListLedger(r.Context(), owner, limit)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	type row struct {
		ID            string    `json:"id"`
		Kind          string    `json:"kind"`
		AmountKopecks int64     `json:"amount_kopecks"`
		Reason        string    `json:"reason"`
		PaymentID     string    `json:"payment_id,omitempty"`
		CreatedAt     time.Time `json:"created_at"`
	}
	out := make([]row, 0, len(entries))
	for _, e := range entries {
		out = append(out, row{
			ID: e.ID, Kind: string(e.Kind), AmountKopecks: e.AmountKopecks,
			Reason: e.Reason, PaymentID: e.PaymentID, CreatedAt: e.CreatedAt,
		})
	}
	WriteJSON(w, http.StatusOK, map[string]any{"entries": out})
}

func (h *Handler) PostBillingCheckout(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	var req struct {
		Period string `json:"period"`
	}
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	period := billing.Period(req.Period)
	owner, _ := auth.OwnerTelegramID(r.Context())
	res, err := h.deps.Billing.CreateCheckout(r.Context(), owner, period, "checkout")
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, res)
}

func (h *Handler) PostBillingCancel(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	owner, _ := auth.OwnerTelegramID(r.Context())
	if err := h.deps.Billing.Cancel(r.Context(), owner); err != nil {
		if WriteAppError(w, err) {
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (h *Handler) PostBillingChangePeriod(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	var req struct {
		Period string `json:"period"`
	}
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	if req.Period != "" && req.Period != string(billing.PeriodYear) {
		WriteValidationError(w, "only upgrade to year is supported", nil)
		return
	}
	owner, _ := auth.OwnerTelegramID(r.Context())
	res, err := h.deps.Billing.ChangePeriodToYear(r.Context(), owner)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, res)
}

func (h *Handler) PostYooKassaWebhook(w http.ResponseWriter, r *http.Request) {
	if h.deps.Billing == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "billing unavailable")
		return
	}
	var body struct {
		Event  string `json:"event"`
		Object struct {
			ID string `json:"id"`
		} `json:"object"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		WriteValidationError(w, "invalid webhook body", nil)
		return
	}
	if body.Object.ID == "" {
		WriteValidationError(w, "missing payment id", nil)
		return
	}
	if err := h.deps.Billing.HandleYooKassaWebhook(r.Context(), body.Object.ID); err != nil {
		if errors.Is(err, appbilling.ErrPaymentUnavailable) {
			WriteAppError(w, err)
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, map[string]any{"ok": true})
}
