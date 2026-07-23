package httpapi

import (
	"errors"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/tonatos/instrumenta/backend/internal/application"
	appbilling "github.com/tonatos/instrumenta/backend/internal/application/billing"
	apptrading "github.com/tonatos/instrumenta/backend/internal/application/trading"
	"github.com/tonatos/instrumenta/backend/internal/domain/billing"
	domainnotifications "github.com/tonatos/instrumenta/backend/internal/domain/notifications"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/tinvest"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/yookassa"
	"github.com/tonatos/instrumenta/backend/internal/interfaces/auth"
)

type CredentialStatusResponse struct {
	Fingerprint            string `json:"fingerprint"`
	UpdatedAt              string `json:"updated_at"`
	TradeEnabled           bool   `json:"trade_enabled"`
	TradeCapabilityChecked bool   `json:"trade_capability_checked"`
}

type AuthMeCredentialsResponse struct {
	Sandbox    *CredentialStatusResponse `json:"sandbox,omitempty"`
	Production *CredentialStatusResponse `json:"production,omitempty"`
}

type PutBrokerCredentialRequest struct {
	Token string `json:"token"`
}

func (h *Handler) AuthMe(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok || user == nil {
		WriteUnauthorized(w, "")
		return
	}
	if h.deps.Users != nil {
		_ = h.deps.Users.Upsert(r.Context(), user.TelegramID, user.DisplayName)
	}
	resp := AuthMeResponse{
		TelegramID:  user.TelegramID,
		DisplayName: user.DisplayName,
		Credentials: AuthMeCredentialsResponse{},
	}
	if h.deps.Credentials != nil {
		metas, err := h.deps.Credentials.ListMeta(r.Context(), user.TelegramID)
		if err == nil {
			for _, m := range metas {
				meta := m
				if !meta.TradeCapabilityChecked {
					meta = h.probeCredentialTradeCapability(r, user.TelegramID, meta)
				}
				status := &CredentialStatusResponse{
					Fingerprint:            meta.Fingerprint,
					UpdatedAt:              meta.UpdatedAt,
					TradeEnabled:           meta.TradeEnabled,
					TradeCapabilityChecked: meta.TradeCapabilityChecked,
				}
				switch meta.AccountKind {
				case trading.AccountKindSandbox:
					resp.Credentials.Sandbox = status
				case trading.AccountKindProduction:
					resp.Credentials.Production = status
				}
			}
		}
	}
	// AUTH_DISABLED local: surface env trading tokens as configured when no DB credential.
	if !h.deps.Settings.AuthEnabled() {
		if resp.Credentials.Sandbox == nil && h.deps.Settings.TTradingTokenSandbox != "" {
			resp.Credentials.Sandbox = &CredentialStatusResponse{Fingerprint: "env", UpdatedAt: "", TradeEnabled: true, TradeCapabilityChecked: true}
		}
		if resp.Credentials.Production == nil && h.deps.Settings.TTradingTokenProduction != "" {
			resp.Credentials.Production = &CredentialStatusResponse{Fingerprint: "env", UpdatedAt: "", TradeEnabled: true, TradeCapabilityChecked: true}
		}
	}
	botUsername := h.deps.TelegramBotUsername
	botConfigured := h.deps.Settings.TelegramBotToken != ""
	botStatus := &TelegramBotStatus{
		Configured:  botConfigured,
		BotUsername: botUsername,
		DeepLink:    domainnotifications.BotDeepLink(botUsername),
	}
	if h.deps.Users != nil {
		connected, err := h.deps.Users.IsBotConnected(r.Context(), user.TelegramID)
		if err == nil {
			botStatus.Connected = connected
		}
	}
	resp.TelegramBot = botStatus
	WriteJSON(w, http.StatusOK, resp)
}

func (h *Handler) probeCredentialTradeCapability(r *http.Request, ownerTelegramID int64, meta persistence.BrokerCredentialMeta) persistence.BrokerCredentialMeta {
	if h.deps.Credentials == nil {
		return meta
	}
	token, err := h.deps.Credentials.GetPlaintext(r.Context(), ownerTelegramID, meta.AccountKind)
	if err != nil || token == "" {
		return meta
	}
	client := tinvest.NewSDKClient(token, meta.AccountKind)
	accounts, err := client.ListAccounts(meta.AccountKind)
	if err != nil {
		return meta
	}
	// Empty list is inconclusive — do not persist "read-only".
	if len(accounts) == 0 {
		return meta
	}
	tradeEnabled := trading.TokenCanTrade(accounts)
	if err := h.deps.Credentials.SetTradeCapability(r.Context(), ownerTelegramID, meta.AccountKind, tradeEnabled); err != nil {
		return meta
	}
	meta.TradeEnabled = tradeEnabled
	meta.TradeCapabilityChecked = true
	return meta
}

func (h *Handler) DeleteTelegramBot(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok || user == nil {
		WriteUnauthorized(w, "")
		return
	}
	if h.deps.Users == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "users store unavailable")
		return
	}
	if err := h.deps.Users.MarkBotDisconnected(r.Context(), user.TelegramID); err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) PutBrokerCredential(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok || user == nil {
		WriteUnauthorized(w, "")
		return
	}
	if !h.requireFeature(w, r, billing.FeatureBrokerCredentialsWrite) {
		return
	}
	kind, err := parseAccountKind(chi.URLParam(r, "kind"))
	if err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	if h.deps.Credentials == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "credentials store unavailable")
		return
	}
	var req PutBrokerCredentialRequest
	if err := DecodeBody(r, &req); err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	token := strings.TrimSpace(req.Token)
	if token == "" {
		WriteValidationError(w, "token is required", nil)
		return
	}
	client := tinvest.NewSDKClient(token, kind)
	accounts, err := client.ListAccounts(kind)
	if err != nil {
		WriteValidationError(w, "token rejected by broker: "+err.Error(), map[string]any{"code": "invalid_broker_token"})
		return
	}
	tradeEnabled := trading.TokenCanTrade(accounts)
	meta, err := h.deps.Credentials.Put(r.Context(), user.TelegramID, kind, token, tradeEnabled)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if h.deps.Users != nil {
		_ = h.deps.Users.Upsert(r.Context(), user.TelegramID, user.DisplayName)
	}
	WriteJSON(w, http.StatusOK, CredentialStatusResponse{
		Fingerprint:            meta.Fingerprint,
		UpdatedAt:              meta.UpdatedAt,
		TradeEnabled:           meta.TradeEnabled,
		TradeCapabilityChecked: meta.TradeCapabilityChecked,
	})
}

func (h *Handler) DeleteBrokerCredential(w http.ResponseWriter, r *http.Request) {
	user, ok := auth.UserFromContext(r.Context())
	if !ok || user == nil {
		WriteUnauthorized(w, "")
		return
	}
	kind, err := parseAccountKind(chi.URLParam(r, "kind"))
	if err != nil {
		WriteValidationError(w, err.Error(), nil)
		return
	}
	if h.deps.Credentials == nil {
		WriteClientError(w, http.StatusServiceUnavailable, "credentials store unavailable")
		return
	}
	okDel, err := h.deps.Credentials.Delete(r.Context(), user.TelegramID, kind)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if !okDel {
		WriteNotFound(w, "credential not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func parseAccountKind(raw string) (trading.AccountKind, error) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "sandbox":
		return trading.AccountKindSandbox, nil
	case "production":
		return trading.AccountKindProduction, nil
	default:
		return "", errors.New("kind must be sandbox or production")
	}
}

func WriteAppError(w http.ResponseWriter, err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, application.ErrBrokerCredentialsRequired) || errors.Is(err, apptrading.ErrBrokerCredentialsRequired) || errors.Is(err, persistence.ErrBrokerCredentialMissing) {
		WriteError(w, http.StatusConflict, "Broker credentials required", map[string]any{"code": "broker_credentials_required"})
		return true
	}
	if errors.Is(err, application.ErrBrokerTokenReadOnly) || errors.Is(err, apptrading.ErrBrokerTokenReadOnly) {
		WriteError(w, http.StatusForbidden, "Broker token is read-only", map[string]any{"code": "broker_token_readonly"})
		return true
	}
	if errors.Is(err, appbilling.ErrSubscriptionRequired) {
		WriteError(w, http.StatusPaymentRequired, "Subscription required", map[string]any{"code": "subscription_required"})
		return true
	}
	if errors.Is(err, appbilling.ErrPaymentUnavailable) || errors.Is(err, yookassa.ErrPaymentUnavailable) {
		WriteError(w, http.StatusServiceUnavailable, "Payment unavailable", map[string]any{"code": "payment_unavailable"})
		return true
	}
	if errors.Is(err, appbilling.ErrNoSubscription) {
		WriteError(w, http.StatusBadRequest, "No subscription", map[string]any{"code": "no_subscription"})
		return true
	}
	if errors.Is(err, appbilling.ErrInvalidPeriod) || errors.Is(err, appbilling.ErrInvalidChange) {
		WriteValidationError(w, err.Error(), map[string]any{"code": "invalid_period"})
		return true
	}
	if errors.Is(err, application.ErrPortfolioNotFound) {
		WriteNotFound(w, "Portfolio not found")
		return true
	}
	return false
}
