package auth

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const tokenExpiration = 30 * 24 * time.Hour

type contextKey string

const userContextKey contextKey = "auth_user"

var authExcludedPaths = map[string]bool{
	"/health":                            true,
	"/api/v1/auth/telegram/login":        true,
	"/api/v1/auth/telegram/callback":     true,
	"/api/v1/config":                     true,
	"/api/v1/config/":                    true,
	"/api/v1/billing/webhooks/yookassa":  true,
}

// JWTManager issues and validates access tokens.
type JWTManager struct {
	secret         []byte
	authEnabled    bool
	devTelegramID  int64
	devDisplayName string
}

func NewJWTManager(secret string, authEnabled bool) *JWTManager {
	if secret == "" {
		secret = "insecure-dev-secret-change-me"
	}
	return &JWTManager{
		secret:         []byte(secret),
		authEnabled:    authEnabled,
		devTelegramID:  1,
		devDisplayName: "Dev User",
	}
}

// WithDevUser configures the synthetic user injected when auth is disabled.
func (m *JWTManager) WithDevUser(telegramID int64, displayName string) *JWTManager {
	if telegramID != 0 {
		m.devTelegramID = telegramID
	}
	if displayName != "" {
		m.devDisplayName = displayName
	}
	return m
}

func (m *JWTManager) CreateAccessToken(user User) (string, error) {
	claims := jwt.MapClaims{
		"sub": strconv.FormatInt(user.TelegramID, 10),
		"exp": time.Now().Add(tokenExpiration).Unix(),
		"iat": time.Now().Unix(),
	}
	if user.DisplayName != "" {
		claims["display_name"] = user.DisplayName
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(m.secret)
}

func (m *JWTManager) ParseToken(tokenString string) (*User, error) {
	parsed, err := jwt.Parse(tokenString, func(t *jwt.Token) (any, error) {
		if t.Method != jwt.SigningMethodHS256 {
			return nil, fmt.Errorf("unexpected signing method")
		}
		return m.secret, nil
	})
	if err != nil || !parsed.Valid {
		return nil, fmt.Errorf("invalid token")
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return nil, fmt.Errorf("invalid claims")
	}
	sub, _ := claims["sub"].(string)
	telegramID, err := strconv.ParseInt(sub, 10, 64)
	if err != nil {
		return nil, fmt.Errorf("invalid subject")
	}
	displayName, _ := claims["display_name"].(string)
	return &User{TelegramID: telegramID, DisplayName: displayName}, nil
}

func (m *JWTManager) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if isExcludedPath(r.URL.Path) {
			next.ServeHTTP(w, r)
			return
		}
		if !m.authEnabled {
			user := &User{TelegramID: m.devTelegramID, DisplayName: m.devDisplayName}
			ctx := context.WithValue(r.Context(), userContextKey, user)
			ctx = WithOwnerTelegramID(ctx, user.TelegramID)
			next.ServeHTTP(w, r.WithContext(ctx))
			return
		}
		token := bearerToken(r)
		if token == "" {
			writeUnauthorized(w)
			return
		}
		user, err := m.ParseToken(token)
		if err != nil {
			writeUnauthorized(w)
			return
		}
		ctx := context.WithValue(r.Context(), userContextKey, user)
		ctx = WithOwnerTelegramID(ctx, user.TelegramID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func UserFromContext(ctx context.Context) (*User, bool) {
	user, ok := ctx.Value(userContextKey).(*User)
	return user, ok
}

func isExcludedPath(path string) bool {
	if authExcludedPaths[path] {
		return true
	}
	if strings.HasSuffix(path, "/") && authExcludedPaths[strings.TrimRight(path, "/")] {
		return true
	}
	return false
}

func bearerToken(r *http.Request) string {
	header := r.Header.Get("Authorization")
	if header == "" {
		return ""
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return ""
	}
	return strings.TrimSpace(header[len(prefix):])
}

func writeUnauthorized(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	_, _ = w.Write([]byte(`{"detail":"Unauthorized","status_code":401}`))
}
