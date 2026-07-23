package httpapi

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/url"

	"github.com/tonatos/instrumenta/backend/internal/interfaces/auth"
)

func (h *Handler) TelegramLogin(w http.ResponseWriter, r *http.Request) {
	if !h.deps.Settings.TelegramOIDCConfigured() {
		WriteUnauthorized(w, "Telegram OIDC is not configured")
		return
	}
	verifier, challenge := auth.GeneratePKCEPair()
	nonceBytes := make([]byte, 16)
	_, _ = rand.Read(nonceBytes)
	nonce := hex.EncodeToString(nonceBytes)
	state, err := auth.CreateOAuthState(verifier, nonce, h.deps.Settings.AuthSecret)
	if err != nil {
		WriteUnauthorized(w, err.Error())
		return
	}
	authURL := auth.BuildAuthorizationURL(
		h.deps.Settings.TelegramOIDCClientID,
		h.deps.Settings.TelegramOIDCRedirectURIResolved(),
		challenge,
		state,
		nonce,
	)
	http.Redirect(w, r, authURL, http.StatusFound)
}

func (h *Handler) TelegramCallback(w http.ResponseWriter, r *http.Request) {
	frontendCallback := fmt.Sprintf("%s/login/callback", trimRightSlash(h.deps.Settings.PublicAppURL))
	q := r.URL.Query()
	if errVal := q.Get("error"); errVal != "" {
		desc := q.Get("error_description")
		if desc == "" {
			desc = errVal
		}
		http.Redirect(w, r, frontendErrorURL(frontendCallback, errVal, desc), http.StatusFound)
		return
	}
	code := q.Get("code")
	oauthState := q.Get("state")
	if code == "" || oauthState == "" {
		http.Redirect(w, r, frontendErrorURL(frontendCallback, "missing_code", "Telegram не вернул код авторизации."), http.StatusFound)
		return
	}
	parsed, err := auth.ParseOAuthState(oauthState, h.deps.Settings.AuthSecret)
	if err != nil {
		http.Redirect(w, r, frontendErrorURL(frontendCallback, "auth_failed", err.Error()), http.StatusFound)
		return
	}
	client := h.deps.HTTPClient
	if client == nil {
		client = http.DefaultClient
	}
	user, err := auth.ExchangeAuthorizationCode(
		r.Context(),
		client,
		code,
		parsed.CodeVerifier,
		parsed.Nonce,
		h.deps.Settings.TelegramOIDCClientID,
		h.deps.Settings.TelegramOIDCClientSecret,
		h.deps.Settings.TelegramOIDCRedirectURIResolved(),
	)
	if err != nil {
		http.Redirect(w, r, frontendErrorURL(frontendCallback, "auth_failed", err.Error()), http.StatusFound)
		return
	}
	token, err := h.deps.JWT.CreateAccessToken(auth.User{
		TelegramID:  user.TelegramID,
		DisplayName: user.DisplayName,
	})
	if err != nil {
		http.Redirect(w, r, frontendErrorURL(frontendCallback, "auth_failed", err.Error()), http.StatusFound)
		return
	}
	if h.deps.Users != nil {
		_ = h.deps.Users.Upsert(r.Context(), user.TelegramID, user.DisplayName)
	}
	redirectTo := fmt.Sprintf("%s#access_token=%s", frontendCallback, url.QueryEscape(token))
	http.Redirect(w, r, redirectTo, http.StatusFound)
}

func (h *Handler) Logout(w http.ResponseWriter, r *http.Request) {
	http.Redirect(w, r, trimRightSlash(h.deps.Settings.PublicAppURL)+"/login", http.StatusFound)
}

func frontendErrorURL(callback, errCode, description string) string {
	return fmt.Sprintf("%s?error=%s&error_description=%s",
		callback,
		url.QueryEscape(errCode),
		url.QueryEscape(description),
	)
}

func trimRightSlash(s string) string {
	for len(s) > 0 && s[len(s)-1] == '/' {
		s = s[:len(s)-1]
	}
	return s
}
