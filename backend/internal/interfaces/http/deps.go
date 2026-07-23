package httpapi

import (
	"net/http"

	"github.com/tonatos/instrumenta/backend/internal/application"
	appbilling "github.com/tonatos/instrumenta/backend/internal/application/billing"
	apptrading "github.com/tonatos/instrumenta/backend/internal/application/trading"
	appmarket "github.com/tonatos/instrumenta/backend/internal/application/market"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
	"github.com/tonatos/instrumenta/backend/internal/interfaces/auth"
	"github.com/tonatos/instrumenta/backend/internal/interfaces/config"
)

// Deps wires application services into HTTP handlers.
type Deps struct {
	Settings      config.Settings
	JWT           *auth.JWTManager
	Bonds         application.BondService
	Favorites     application.FavoritesRepository
	Portfolios    application.PortfolioService
	Trading       application.TradingService
	Notifications application.NotificationsRepository
	MarketRadar   application.MarketRadarService
	KeyRates          *appmarket.KeyRateService
	Credentials       *persistence.BrokerCredentialsRepository
	Users             *persistence.UserRepository
	TokenSource       apptrading.TokenSource
	Billing           *appbilling.Service
	TelegramBotUsername string
	// HTTPClient is used for Telegram OIDC token exchange (optional TELEGRAM_HTTP_PROXY).
	HTTPClient *http.Client
}

// Handler serves HTTP API endpoints.
type Handler struct {
	deps Deps
}

func NewHandler(deps Deps) *Handler {
	return &Handler{deps: deps}
}
