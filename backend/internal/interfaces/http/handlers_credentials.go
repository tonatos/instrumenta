package httpapi

import (
	"errors"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/tonatos/bond-monitor/backend/internal/application"
	apptrading "github.com/tonatos/bond-monitor/backend/internal/application/trading"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

type CredentialStatusResponse struct {
	Fingerprint string `json:"fingerprint"`
	UpdatedAt   string `json:"updated_at"`
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
				status := &CredentialStatusResponse{Fingerprint: m.Fingerprint, UpdatedAt: m.UpdatedAt}
				switch m.AccountKind {
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
			resp.Credentials.Sandbox = &CredentialStatusResponse{Fingerprint: "env", UpdatedAt: ""}
		}
		if resp.Credentials.Production == nil && h.deps.Settings.TTradingTokenProduction != "" {
			resp.Credentials.Production = &CredentialStatusResponse{Fingerprint: "env", UpdatedAt: ""}
		}
	}
	WriteJSON(w, http.StatusOK, resp)
}

func (h *Handler) PutBrokerCredential(w http.ResponseWriter, r *http.Request) {
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
	if _, err := client.ListAccounts(kind); err != nil {
		WriteValidationError(w, "token rejected by broker: "+err.Error(), map[string]any{"code": "invalid_broker_token"})
		return
	}
	meta, err := h.deps.Credentials.Put(r.Context(), user.TelegramID, kind, token)
	if err != nil {
		WriteClientError(w, http.StatusBadRequest, err.Error())
		return
	}
	if h.deps.Users != nil {
		_ = h.deps.Users.Upsert(r.Context(), user.TelegramID, user.DisplayName)
	}
	WriteJSON(w, http.StatusOK, CredentialStatusResponse{Fingerprint: meta.Fingerprint, UpdatedAt: meta.UpdatedAt})
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
	if errors.Is(err, application.ErrPortfolioNotFound) {
		WriteNotFound(w, "Portfolio not found")
		return true
	}
	return false
}
