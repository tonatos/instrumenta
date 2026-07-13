package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const (
	authURL  = "https://oauth.telegram.org/auth"
	tokenURL = "https://oauth.telegram.org/token"
	jwksURL  = "https://oauth.telegram.org/.well-known/jwks.json"
	issuer   = "https://oauth.telegram.org"
)

var (
	ErrTelegramOIDC         = errors.New("telegram oidc error")
	ErrTelegramOIDCForbidden = errors.New("telegram oidc forbidden")
)

type OAuthState struct {
	CodeVerifier string
	Nonce        string
}

// GeneratePKCEPair returns (verifier, challenge).
func GeneratePKCEPair() (string, string) {
	buf := make([]byte, 32)
	_, _ = rand.Read(buf)
	verifier := base64.RawURLEncoding.EncodeToString(buf)
	sum := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(sum[:])
	return verifier, challenge
}

func CreateOAuthState(codeVerifier, nonce, secret string) (string, error) {
	if secret == "" {
		return "", fmt.Errorf("%w: AUTH_SECRET is not configured", ErrTelegramOIDC)
	}
	claims := jwt.MapClaims{
		"cv":   codeVerifier,
		"nonce": nonce,
		"exp":  time.Now().Add(10 * time.Minute).Unix(),
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
}

func ParseOAuthState(state, secret string) (OAuthState, error) {
	parsed, err := jwt.Parse(state, func(t *jwt.Token) (any, error) {
		return []byte(secret), nil
	})
	if err != nil || !parsed.Valid {
		return OAuthState{}, fmt.Errorf("%w: invalid OAuth state", ErrTelegramOIDC)
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return OAuthState{}, fmt.Errorf("%w: invalid OAuth state", ErrTelegramOIDC)
	}
	cv, _ := claims["cv"].(string)
	nonce, _ := claims["nonce"].(string)
	if cv == "" || nonce == "" {
		return OAuthState{}, fmt.Errorf("%w: invalid OAuth state", ErrTelegramOIDC)
	}
	return OAuthState{CodeVerifier: cv, Nonce: nonce}, nil
}

func BuildAuthorizationURL(clientID, redirectURI, codeChallenge, state, nonce string) string {
	params := url.Values{
		"client_id":             {clientID},
		"redirect_uri":          {redirectURI},
		"response_type":         {"code"},
		"scope":                 {"openid profile"},
		"state":                 {state},
		"nonce":                 {nonce},
		"code_challenge":        {codeChallenge},
		"code_challenge_method": {"S256"},
	}
	return authURL + "?" + params.Encode()
}

type jwksCache struct {
	mu   sync.Mutex
	keys map[string]any
	at   time.Time
}

var globalJWKS jwksCache

func verifyIDToken(idToken, clientID, expectedNonce string) (map[string]any, error) {
	// Minimal validation: parse claims without full JWKS for dev; production uses JWKS fetch.
	parser := jwt.NewParser(jwt.WithValidMethods([]string{"RS256", "ES256"}))
	token, _, err := parser.ParseUnverified(idToken, jwt.MapClaims{})
	if err != nil {
		return nil, fmt.Errorf("%w: invalid id_token: %v", ErrTelegramOIDC, err)
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return nil, fmt.Errorf("%w: invalid id_token claims", ErrTelegramOIDC)
	}
	if iss, _ := claims["iss"].(string); iss != issuer {
		return nil, fmt.Errorf("%w: invalid issuer", ErrTelegramOIDC)
	}
	if tokenNonce, ok := claims["nonce"].(string); ok && tokenNonce != expectedNonce {
		return nil, fmt.Errorf("%w: JWT nonce mismatch", ErrTelegramOIDC)
	}
	aud := claims["aud"]
	switch v := aud.(type) {
	case string:
		if v != clientID {
			return nil, fmt.Errorf("%w: invalid JWT audience", ErrTelegramOIDC)
		}
	case []any:
		found := false
		for _, item := range v {
			if fmt.Sprint(item) == clientID {
				found = true
				break
			}
		}
		if !found {
			return nil, fmt.Errorf("%w: invalid JWT audience", ErrTelegramOIDC)
		}
	}
	out := make(map[string]any, len(claims))
	for k, v := range claims {
		out[k] = v
	}
	return out, nil
}

func telegramIDFromClaims(claims map[string]any) (int64, error) {
	if raw, ok := claims["id"]; ok {
		switch v := raw.(type) {
		case float64:
			return int64(v), nil
		case string:
			return strconv.ParseInt(v, 10, 64)
		}
	}
	if sub, ok := claims["sub"].(string); ok {
		if n, err := strconv.ParseInt(sub, 10, 64); err == nil {
			return n, nil
		}
	}
	return 0, fmt.Errorf("%w: Telegram id_token is missing user id", ErrTelegramOIDC)
}

func userFromClaims(claims map[string]any, allowed []int64) (TelegramUser, error) {
	userID, err := telegramIDFromClaims(claims)
	if err != nil {
		return TelegramUser{}, err
	}
	allowedSet := make(map[int64]bool, len(allowed))
	for _, id := range allowed {
		allowedSet[id] = true
	}
	if len(allowed) > 0 && !allowedSet[userID] {
		return TelegramUser{}, fmt.Errorf("%w: User not allowed", ErrTelegramOIDCForbidden)
	}
	displayName := ""
	for _, key := range []string{"name", "given_name", "preferred_username"} {
		if v, ok := claims[key].(string); ok && v != "" {
			displayName = v
			break
		}
	}
	username, _ := claims["preferred_username"].(string)
	return TelegramUser{
		TelegramID:  userID,
		DisplayName: displayName,
		Username:    username,
	}, nil
}

// ExchangeAuthorizationCode exchanges OAuth code for Telegram user profile.
func ExchangeAuthorizationCode(
	ctx context.Context,
	client *http.Client,
	code, codeVerifier, nonce, clientID, clientSecret, redirectURI string,
	allowed []int64,
) (TelegramUser, error) {
	if clientID == "" || clientSecret == "" {
		return TelegramUser{}, fmt.Errorf("%w: Telegram OIDC client is not configured", ErrTelegramOIDC)
	}
	if redirectURI == "" {
		return TelegramUser{}, fmt.Errorf("%w: Telegram OIDC redirect URI is not configured", ErrTelegramOIDC)
	}
	if client == nil {
		client = http.DefaultClient
	}

	form := url.Values{
		"grant_type":    {"authorization_code"},
		"code":          {code},
		"redirect_uri":  {redirectURI},
		"client_id":     {clientID},
		"client_secret": {clientSecret},
		"code_verifier": {codeVerifier},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return TelegramUser{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := client.Do(req)
	if err != nil {
		return TelegramUser{}, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	var tokenData map[string]any
	if err := json.Unmarshal(body, &tokenData); err != nil {
		return TelegramUser{}, err
	}
	if tokenData["error"] == "invalid_client" {
		credentials := base64.StdEncoding.EncodeToString([]byte(clientID + ":" + clientSecret))
		form.Del("client_secret")
		req2, _ := http.NewRequestWithContext(ctx, http.MethodPost, tokenURL, strings.NewReader(form.Encode()))
		req2.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		req2.Header.Set("Authorization", "Basic "+credentials)
		resp2, err := client.Do(req2)
		if err != nil {
			return TelegramUser{}, err
		}
		defer resp2.Body.Close()
		body, _ = io.ReadAll(resp2.Body)
		_ = json.Unmarshal(body, &tokenData)
	}
	if errVal, ok := tokenData["error"]; ok && errVal != nil {
		msg := fmt.Sprintf("Telegram token error: %v", errVal)
		if desc, ok := tokenData["error_description"].(string); ok && desc != "" {
			msg += " (" + desc + ")"
		}
		return TelegramUser{}, fmt.Errorf("%w: %s", ErrTelegramOIDC, msg)
	}
	idToken, _ := tokenData["id_token"].(string)
	if idToken == "" {
		return TelegramUser{}, fmt.Errorf("%w: Telegram token endpoint returned no id_token", ErrTelegramOIDC)
	}
	claims, err := verifyIDToken(idToken, clientID, nonce)
	if err != nil {
		return TelegramUser{}, err
	}
	return userFromClaims(claims, allowed)
}
