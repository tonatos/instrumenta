package httpapi

import (
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

// NewRouter builds the chi router with all API routes.
func NewRouter(deps Deps, logger *slog.Logger) http.Handler {
	h := NewHandler(deps)
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(RecoverMiddleware(logger))
	r.Use(RequestLogger(logger))
	r.Use(CORSMiddleware(deps.Settings))
	if deps.JWT != nil {
		r.Use(deps.JWT.Middleware)
	}

	r.Get("/health", h.Health)

	r.Route("/api/v1", func(r chi.Router) {
		r.Get("/config", h.GetConfig)
		r.Get("/config/", h.GetConfig)
		r.Get("/market-radar", h.GetMarketRadar)

		r.Route("/auth", func(r chi.Router) {
			r.Get("/telegram/login", h.TelegramLogin)
			r.Get("/telegram/callback", h.TelegramCallback)
			r.Get("/me", h.AuthMe)
			r.Get("/logout", h.Logout)
		})

		r.Route("/bonds", func(r chi.Router) {
			r.Get("/", h.ListBonds)
			r.Get("/by-isins", h.BondsByISINs)
			r.Get("/{secid}", h.GetBond)
			r.Post("/refresh", h.RefreshBonds)
		})

		r.Route("/favorites", func(r chi.Router) {
			r.Get("/", h.ListFavorites)
			r.Put("/{isin}", h.AddFavorite)
			r.Delete("/{isin}", h.RemoveFavorite)
		})

		r.Route("/ratings", func(r chi.Router) {
			r.Post("/refresh", h.RefreshRatings)
		})

		r.Route("/portfolios", func(r chi.Router) {
			r.Get("/", h.ListPortfolios)
			r.Post("/", h.CreatePortfolio)
			r.Get("/{portfolio_id}", h.GetPortfolio)
			r.Delete("/{portfolio_id}", h.DeletePortfolio)
			r.Patch("/{portfolio_id}", h.UpdatePortfolio)
			r.Post("/{portfolio_id}/clear", h.ClearPositions)
			r.Post("/{portfolio_id}/positions", h.AddPosition)
			r.Delete("/{portfolio_id}/positions/{isin}", h.RemovePosition)
			r.Patch("/{portfolio_id}/positions/{isin}/put-offer-decision", h.SetPutOfferDecision)
			r.Post("/{portfolio_id}/slots/override", h.SetSlotOverride)
			r.Post("/{portfolio_id}/slots/reset-all", h.ResetAllSlotOverrides)
			r.Post("/{portfolio_id}/auto-compose", h.AutoCompose)
			r.Get("/{portfolio_id}/plan", h.GetPlan)
			r.Get("/{portfolio_id}/notifications", h.ListNotifications)

			r.Get("/{portfolio_id}/account-preview", h.AccountPreview)
			r.Post("/{portfolio_id}/clear-account", h.ClearAccount)
			r.Post("/{portfolio_id}/attach", h.AttachAccount)
			r.Post("/{portfolio_id}/detach", h.DetachAccount)
			r.Post("/{portfolio_id}/sandbox-pay-in", h.SandboxPayIn)
			r.Get("/{portfolio_id}/advice", h.GetAdvice)
			r.Get("/{portfolio_id}/trading-state", h.GetTradingState)
			r.Post("/{portfolio_id}/deploy-sessions", h.CreateDeploySession)
			r.Get("/{portfolio_id}/deploy-sessions/active", h.GetActiveDeploySession)
			r.Post("/{portfolio_id}/deploy-sessions/{session_id}/refresh", h.RefreshDeploySession)
			r.Delete("/{portfolio_id}/deploy-sessions/{session_id}", h.CancelDeploySession)
			r.Post("/{portfolio_id}/deploy-sessions/{session_id}/items/{item_id}/skip", h.SkipDeploySessionItem)
			r.Post("/{portfolio_id}/risk-alerts/{isin}/acknowledge", h.AcknowledgeRiskAlert)
			r.Post("/{portfolio_id}/orders/preview", h.PreviewOrder)
			r.Post("/{portfolio_id}/orders/place", h.PlaceOrder)
			r.Post("/{portfolio_id}/orders/{order_id}/cancel", h.CancelOrder)
			r.Post("/{portfolio_id}/positions/{isin}/sell-preview", h.SellPositionPreview)
			r.Get("/{portfolio_id}/positions/{isin}/sell-quote", h.SellQuote)
			r.Get("/{portfolio_id}/performance", h.Performance)
			r.Get("/{portfolio_id}/account-operations", h.AccountOperations)
		})

		r.Post("/calculator/portfolio", h.CalculatePortfolio)

		r.Route("/accounts", func(r chi.Router) {
			r.Get("/", h.ListAccounts)
			r.Post("/sandbox", h.CreateSandboxAccount)
			r.Delete("/sandbox/{account_id}", h.DeleteSandboxAccount)
		})

		r.Post("/notifications/{notification_id}/read", h.MarkNotificationRead)
		r.Post("/notifications/{notification_id}/dismiss", h.DismissNotification)
	})

	return r
}
