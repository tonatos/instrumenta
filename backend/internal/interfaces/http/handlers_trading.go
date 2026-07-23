package httpapi

import (
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/billing"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
)

func (h *Handler) ListAccounts(w http.ResponseWriter, r *http.Request) {
	if !h.requireFeature(w, r, billing.FeaturePortfolioAttach) {
		return
	}
	kind := r.URL.Query().Get("kind")
	if kind == "" {
		kind = "sandbox"
	}
	accounts, err := h.deps.Trading.ListAccounts(r.Context(), trading.AccountKind(kind))
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, accounts)
}

func (h *Handler) CreateSandboxAccount(w http.ResponseWriter, r *http.Request) {
	if !h.requireFeature(w, r, billing.FeaturePortfolioAttach) {
		return
	}
	var req struct {
		InitialAmountRub float64 `json:"initial_amount_rub"`
		Name             *string `json:"name"`
	}
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	account, err := h.deps.Trading.CreateSandboxAccount(r.Context(), req.InitialAmountRub, req.Name)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, account)
}

func (h *Handler) DeleteSandboxAccount(w http.ResponseWriter, r *http.Request) {
	if !h.requireFeature(w, r, billing.FeaturePortfolioAttach) {
		return
	}
	accountID := chi.URLParam(r, "account_id")
	result, err := h.deps.Trading.DeleteSandboxAccount(r.Context(), accountID)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, result)
}

func (h *Handler) AccountPreview(w http.ResponseWriter, r *http.Request) {
	if !h.requireFeature(w, r, billing.FeaturePortfolioAttach) {
		return
	}
	portfolioID := chi.URLParam(r, "portfolio_id")
	accountID := r.URL.Query().Get("account_id")
	kind := r.URL.Query().Get("kind")
	if kind == "" {
		kind = "sandbox"
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	preview, err := h.deps.Trading.GetAccountPreview(r.Context(), portfolioID, accountID, trading.AccountKind(kind), universe.Bonds)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, preview)
}

func (h *Handler) ClearAccount(w http.ResponseWriter, r *http.Request) {
	if !h.requireFeature(w, r, billing.FeaturePortfolioAttach) {
		return
	}
	portfolioID := chi.URLParam(r, "portfolio_id")
	var req struct {
		AccountID string   `json:"account_id"`
		Kind      string   `json:"kind"`
		PayInRub  *float64 `json:"pay_in_rub"`
	}
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	if req.Kind == "" {
		req.Kind = "sandbox"
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	preview, err := h.deps.Trading.ClearAccountForAttach(r.Context(), portfolioID, req.AccountID, trading.AccountKind(req.Kind), req.PayInRub, universe.Bonds)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, preview)
}

func (h *Handler) AttachAccount(w http.ResponseWriter, r *http.Request) {
	if !h.requireFeature(w, r, billing.FeaturePortfolioAttach) {
		return
	}
	portfolioID := chi.URLParam(r, "portfolio_id")
	var req map[string]any
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	accountID, _ := req["account_id"].(string)
	kind, _ := req["kind"].(string)
	if kind == "" {
		kind = "sandbox"
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	p, err := h.deps.Trading.AttachAccount(
		r.Context(), portfolioID, accountID, trading.AccountKind(kind), universe.Bonds,
		keyRate, taxRate, time.Now(),
	)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) DetachAccount(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Trading.DetachAccount(r.Context(), portfolioID)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, PortfolioToResponse(p, time.Now()))
}

func (h *Handler) SandboxPayIn(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	var req struct {
		AmountRub float64 `json:"amount_rub"`
	}
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	result, err := h.deps.Trading.SandboxPayIn(r.Context(), portfolioID, req.AmountRub)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, result)
}

func (h *Handler) GetAdvice(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), portfolioID)
	if err != nil || p == nil {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	if !h.requireTradingPortfolioAccess(w, r, p) {
		return
	}
	durationPolicy := DurationPolicyForPortfolio(*p, r.URL.Query().Get("rate_scenario"))
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	result, err := h.deps.Trading.GetAdvice(
		r.Context(), portfolioID, universe.Bonds,
		keyRate, taxRate,
		time.Now(), durationPolicy,
	)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, AdviceToResponse(result))
}

func (h *Handler) GetTradingState(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	p, err := h.deps.Portfolios.GetPortfolio(r.Context(), portfolioID)
	if err != nil || p == nil {
		WriteNotFound(w, "Portfolio not found")
		return
	}
	if !h.requireTradingPortfolioAccess(w, r, p) {
		return
	}
	durationPolicy := DurationPolicyForPortfolio(*p, r.URL.Query().Get("rate_scenario"))
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	result, err := h.deps.Trading.GetTradingState(
		r.Context(), portfolioID, universe.Bonds,
		keyRate, taxRate,
		time.Now(), durationPolicy,
	)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, TradingStateResponse{
		Plan:   PlanToResponse(result.Plan),
		Advice: AdviceToResponse(result.Advice),
	})
}

func (h *Handler) CreateDeploySession(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	session, err := h.deps.Trading.CreateDeploySession(
		r.Context(), portfolioID, universe.Bonds,
		keyRate, taxRate, time.Now(),
	)
	if err != nil {
		if errors.Is(err, application.ErrDeploySessionConflict) {
			WriteConflict(w, err.Error())
			return
		}
		if errors.Is(err, application.ErrDeploySessionEmpty) {
			WriteValidationError(w, err.Error(), nil)
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	resp := DeploySessionToResponse(&session)
	WriteJSON(w, http.StatusCreated, resp)
}

func (h *Handler) GetActiveDeploySession(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	session, err := h.deps.Trading.GetActiveDeploySession(r.Context(), portfolioID)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if session == nil {
		WriteNotFound(w, "Active deploy session not found")
		return
	}
	WriteJSON(w, http.StatusOK, DeploySessionToResponse(session))
}

func (h *Handler) RefreshDeploySession(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	sessionID := chi.URLParam(r, "session_id")
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	keyRate, taxRate := h.resolveMarketRates(r.Context())
	session, err := h.deps.Trading.RefreshDeploySession(
		r.Context(), portfolioID, sessionID, universe.Bonds,
		keyRate, taxRate, time.Now(),
	)
	if err != nil {
		if errors.Is(err, application.ErrDeploySessionNotFound) {
			WriteNotFound(w, err.Error())
			return
		}
		if errors.Is(err, application.ErrDeploySessionEmpty) {
			WriteValidationError(w, err.Error(), nil)
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, DeploySessionToResponse(&session))
}

func (h *Handler) CancelDeploySession(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	sessionID := chi.URLParam(r, "session_id")
	session, err := h.deps.Trading.CancelDeploySession(r.Context(), portfolioID, sessionID)
	if err != nil {
		if errors.Is(err, application.ErrDeploySessionNotFound) {
			WriteNotFound(w, err.Error())
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, DeploySessionToResponse(&session))
}

func (h *Handler) SkipDeploySessionItem(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	sessionID := chi.URLParam(r, "session_id")
	itemID := chi.URLParam(r, "item_id")
	session, err := h.deps.Trading.SkipDeploySessionItem(r.Context(), portfolioID, sessionID, itemID)
	if err != nil {
		if errors.Is(err, application.ErrDeploySessionNotFound) {
			WriteNotFound(w, err.Error())
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, DeploySessionToResponse(&session))
}

func (h *Handler) AcknowledgeRiskAlert(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	isin := chi.URLParam(r, "isin")
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err := h.deps.Trading.AcknowledgeRiskAlert(r.Context(), portfolioID, isin, universe.Bonds); err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) PreviewOrder(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	var req PlaceOrderRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	result, err := h.deps.Trading.PreviewOrder(r.Context(), portfolioID, universe.Bonds, req.ISIN, req.Direction, req.Lots, req.PricePct, req.FIGI)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, result)
}

func (h *Handler) PlaceOrder(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	var req PlaceOrderRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	result, err := h.deps.Trading.PlaceOrder(r.Context(), portfolioID, universe.Bonds, req.ISIN, req.Direction, req.Lots, req.PricePct, req.FIGI, req.SuggestionID)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusCreated, result)
}

func (h *Handler) CancelOrder(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	orderID := chi.URLParam(r, "order_id")
	if err := h.deps.Trading.CancelOrder(r.Context(), portfolioID, orderID); err != nil {
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, map[string]string{"order_id": orderID, "status": "cancelled"})
}

func (h *Handler) SellPositionPreview(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	isin := chi.URLParam(r, "isin")
	var req SellPositionRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	result, err := h.deps.Trading.PreviewSellPosition(r.Context(), portfolioID, isin, universe.Bonds, req.Lots, req.PricePct, time.Now())
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, result)
}

func (h *Handler) SellQuote(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	isin := chi.URLParam(r, "isin")
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	result, err := h.deps.Trading.GetSellQuote(r.Context(), portfolioID, isin, universe.Bonds)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, result)
}

func (h *Handler) Performance(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	result, err := h.deps.Trading.GetPerformance(r.Context(), portfolioID)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	WriteJSON(w, http.StatusOK, result)
}

func (h *Handler) AccountOperations(w http.ResponseWriter, r *http.Request) {
	portfolioID := chi.URLParam(r, "portfolio_id")
	if !h.gateTradingPortfolioID(w, r, portfolioID) {
		return
	}
	universe, err := h.deps.Bonds.LoadUniverse(r.Context())
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	operations, err := h.deps.Trading.GetAccountOperations(r.Context(), portfolioID)
	if err != nil {
		if WriteAppError(w, err) {
			return
		}
		if errors.Is(err, application.ErrPortfolioNotFound) {
			WriteNotFound(w, "Portfolio not found")
			return
		}
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	bondsByFIGI := make(map[string]bonds.BondRecord)
	for _, bond := range universe.Bonds {
		if bond.FIGI != "" {
			bondsByFIGI[bond.FIGI] = bond
		}
	}
	out := make([]AccountOperationResponse, 0, len(operations))
	for _, op := range operations {
		out = append(out, AccountOperationToResponse(op, bondsByFIGI))
	}
	WriteJSON(w, http.StatusOK, AccountOperationsResponse{Operations: out})
}
