package httpapi

import (
	"net/http"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
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
	HTTPClient    *http.Client
}

// Handler serves HTTP API endpoints.
type Handler struct {
	deps Deps
}

func NewHandler(deps Deps) *Handler {
	return &Handler{deps: deps}
}
