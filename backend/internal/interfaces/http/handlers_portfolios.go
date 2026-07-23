package httpapi

import (
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

func (h *Handler) ListPortfolios(w http.ResponseWriter, r *http.Request) {
	portfolios, err := h.deps.Portfolios.ListPortfolios(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	out := make([]PortfolioResponse, 0, len(portfolios))
	today := time.Now()
	owner, _ := auth.OwnerTelegramID(r.Context())
	for _, p := range portfolios {
		resp := PortfolioToResponse(p, today)
		resp.AccessLocked = h.accessLockedForOwner(r, owner, p)
		out = append(out, resp)
	}
	WriteJSON(w, http.StatusOK, out)
}

func (h *Handler) CreatePortfolio(w http.ResponseWriter, r *http.Request) {
	var req CreatePortfolioRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	horizon, err := time.Parse("2006-01-02", req.HorizonDate)
	if err != nil {
		WriteValidationError(w, "invalid horizon_date", nil)
		return
	}
	apiTrade := true
	if req.APITradeOnly != nil {
		apiTrade = *req.APITradeOnly
	}
	turbo := false
	if req.TurboEntryEnabled != nil {
		turbo = *req.TurboEntryEnabled
	}
	p, err := h.deps.Portfolios.CreatePortfolio(r.Context(), application.CreatePortfolioParams{
		Name:                     req.Name,
		InitialAmountRub:         req.InitialAmountRub,
		HorizonDate:              shared.DateOnly(horizon),
		RiskProfile:              ParseRiskProfile(req.RiskProfile),
		APITradeOnly:             apiTrade,
		TurboEntryEnabled:        turbo,
		MaxWeightedDurationYears: req.MaxWeightedDurationYears,
		TargetDurationYears:      req.TargetDurationYears,
	})
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) GetPortfolio(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), id)
	if err != nil || p == nil {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	if !h.requireTradingPortfolioAccess(w, r, p) {
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(*p, time.Now()))
}

func (h *Handler) DeletePortfolio(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	ok, err := h.deps.Portfolios.DeletePortfolio(r.Context(), id)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !ok {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) UpdatePortfolio(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, id) {
		return
	}
	var req UpdatePortfolioRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	params := application.UpdatePortfolioParams{
		Name:                     req.Name,
		InitialAmountRub:         req.InitialAmountRub,
		APITradeOnly:             req.APITradeOnly,
		TurboEntryEnabled:        req.TurboEntryEnabled,
		MaxWeightedDurationYears: req.MaxWeightedDurationYears,
		TargetDurationYears:      req.TargetDurationYears,
	}
	if req.HorizonDate != nil {
		horizon, err := time.Parse("2006-01-02", *req.HorizonDate)
		if err != nil {
			WriteValidationError(w, "invalid horizon_date", nil)
			return
		}
		h := shared.DateOnly(horizon)
		params.HorizonDate = &h
	}
	if req.RiskProfile != nil {
		rp := ParseRiskProfile(*req.RiskProfile)
		params.RiskProfile = &rp
	}
	if req.MaxWeightedDurationYears != nil || req.MaxWeightedDurationYears == nil {
		params.SetMaxWeightedDuration = true
	}
	if req.TargetDurationYears != nil || req.TargetDurationYears == nil {
		params.SetTargetDuration = true
	}
	p, err := h.deps.Portfolios.UpdatePortfolio(r.Context(), id, params)
	if err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) ClearPositions(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Portfolios.ClearPositions(r.Context(), id)
	if err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) AddPosition(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	var req AddPositionRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	p, err := h.deps.Portfolios.AddPosition(r.Context(), id, universe.Bonds, req.ISIN, req.Lots, time.Now())
	if err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		if errors.Is(err, application.ErrBondNotFound) {
			WriteNotFound(w, "Bond "+req.ISIN+" not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) RemovePosition(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	isin := chi.URLParam(r, "isin")
	if err := h.deps.Portfolios.RemovePosition(r.Context(), id, isin); err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		if errors.Is(err, application.ErrPositionNotFound) {
			WriteNotFound(w, "Position "+isin+" not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) SetPutOfferDecision(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	isin := chi.URLParam(r, "isin")
	var req SetPutOfferDecisionRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	p, err := h.deps.Portfolios.SetPutOfferDecision(r.Context(), id, isin, req.Decision)
	if err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		if errors.Is(err, application.ErrPositionNotFound) {
			WriteNotFound(w, "Position "+isin+" not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) SetSlotOverride(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	var req SetSlotOverrideRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), id)
	if err != nil || p == nil {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	durationPolicy := DurationPolicyForPortfolio(*p, r.URL.Query().Get("rate_scenario"))
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	updated, err := h.deps.Portfolios.SetSlotOverride(
		r.Context(), id, req.SourcePositionISIN, req.ConfirmedISIN,
		universe.Bonds, keyRate, taxRate,
		time.Now(), durationPolicy,
	)
	if err != nil {
		var slotErr application.SlotOverrideError
		if errors.As(err, &slotErr) {
			WriteValidationError(w, slotErr.Message, map[string]any{"code": slotErr.Code})
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(updated, time.Now()))
}

func (h *Handler) ResetAllSlotOverrides(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Portfolios.ResetAllSlotOverrides(r.Context(), id)
	if err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) AutoCompose(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), id)
	if err != nil || p == nil {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	durationPolicy := DurationPolicyForPortfolio(*p, r.URL.Query().Get("rate_scenario"))
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	updated, err := h.deps.Portfolios.AutoComposePortfolio(
		r.Context(), id, universe.Bonds,
		keyRate, taxRate,
		time.Now(), durationPolicy,
	)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(updated, time.Now()))
}

func (h *Handler) GetPlan(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, id) {
		return
	}
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), id)
	if err != nil || p == nil {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	durationPolicy := DurationPolicyForPortfolio(*p, r.URL.Query().Get("rate_scenario"))
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	today := time.Now()
	var plan portfolio.PortfolioPlan
	plan, err = h.deps.Portfolios.BuildPortfolioPlan(
		r.Context(), id, universe.Bonds,
		keyRate, taxRate,
		today, durationPolicy,
	)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PlanToResponse(plan))
}

func (h *Handler) CalculatePortfolio(w http.ResponseWriter, r *http.Request) {
	var req CalculatorRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	today := time.Now()
	ctx := r.Context()
	bondList := make([]bonds.BondRecord, 0, len(req.Secids))
	for _, secid := range req.Secids {
		bond, err := h.deps.Bonds.LoadBySecid(ctx, secid, portfolio.RiskProfileNormal, string(portfolio.RateScenarioHold))
		if err != nil || bond == nil {
			continue
		}
		bondList = append(bondList, *bond)
	}
	hold := portfolio.CalculatePortfolioBudget(bondList, req.BudgetRub, today)
	results := make([]map[string]any, 0, len(hold.Positions))
	for _, p := range hold.Positions {
		results = append(results, map[string]any{
			"secid":             p.Secid,
			"name":              p.Name,
			"lots":              p.Lots,
			"invested_rub":      p.InvestedRub,
			"coupon_income_rub": p.CouponIncomeRub,
			"profit_rub":        p.ProfitRub,
			"hold_days":         p.HoldDays,
		})
	}
	WriteJSON(w, http.StatusOK, CalculatorResponse{
		Results:           results,
		TotalInvestedRub:  hold.TotalInvestedRub,
		TotalProfitRub:    hold.TotalProfitRub,
		PortfolioYieldPct: hold.PortfolioYieldPct,
	})
}
