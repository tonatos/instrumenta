package app

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/application/adapters"
	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	appmarketsignals "github.com/tonatos/bond-monitor/backend/internal/application/market_signals"
	appnotifications "github.com/tonatos/bond-monitor/backend/internal/application/notifications"
	appportfolio "github.com/tonatos/bond-monitor/backend/internal/application/portfolio"
	apptrading "github.com/tonatos/bond-monitor/backend/internal/application/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
	httpapi "github.com/tonatos/bond-monitor/backend/internal/interfaces/http"
)

// App bundles wired runtime dependencies.
type App struct {
	Deps     httpapi.Deps
	DB       *persistence.DB
	Consumer application.NotificationConsumer
}

// Wire opens persistence, runs migrations, and wires application services.
func Wire(ctx context.Context, settings config.Settings, logger *slog.Logger) (*App, error) {
	if logger == nil {
		logger = slog.Default()
	}
	tinvest.SetLogger(logger.With("component", "tinvest"))

	if err := os.MkdirAll(settings.CacheDir, 0o755); err != nil {
		return nil, fmt.Errorf("cache dir: %w", err)
	}

	dsn := NormalizeDSN(settings.DatabaseURL)
	logger.Info("opening database", "dsn", maskDSN(dsn))
	db, err := persistence.Open(dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}
	if err := db.Ping(ctx); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("ping db: %w", err)
	}
	if err := runMigrations(ctx, db); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	logger.Info("database ready")

	portfolioRepo := persistence.NewPortfolioRepository(db)
	favoritesRepo := persistence.NewFavoritesRepository(db)
	notificationsRepo := persistence.NewNotificationsRepository(db)
	deployRepo := persistence.NewDeploySessionRepository(db)
	radarRepo := persistence.NewMarketRadarRepository(db.DB)

	bondInner := appbonds.NewService(
		settings.KeyRate,
		settings.TaxRateFraction(),
		settings.TinkoffToken,
	)
	if logger != nil {
		logger.Info("warming bond universe cache")
	}
	universe := bondInner.LoadUniverse()
	logger.Info("bond cache ready", "universe", len(universe.Bonds))
	portfolioInner := appportfolio.NewService(portfolioRepo)
	tradingInner := apptrading.NewService(
		portfolioRepo,
		deployRepo,
		notificationsRepo,
		settings.TTradingTokenSandbox,
		settings.TTradingTokenProduction,
	)

	jwtManager := auth.NewJWTManager(settings.AuthSecret, settings.AuthEnabled())
	var consumer application.NotificationConsumer
	if settings.RedisURL != "" {
		consumer = appnotifications.NewConsumer(settings.RedisURL, notificationsRepo, logger)
	} else {
		consumer = noopConsumer{}
	}

	getRadar := appmarketsignals.NewGetRadarUseCase(radarRepo, portfolioInner)

	deps := httpapi.Deps{
		Settings:      settings,
		JWT:           jwtManager,
		Bonds:         adapters.NewBondService(bondInner),
		Favorites:     adapters.NewFavoritesRepository(favoritesRepo),
		Portfolios:    adapters.NewPortfolioService(portfolioInner),
		Trading:       tradingInner,
		Notifications: adapters.NewNotificationsRepository(notificationsRepo),
		MarketRadar:   adapters.NewMarketRadarService(getRadar),
		HTTPClient:    &http.Client{Timeout: 20 * time.Second},
	}

	return &App{Deps: deps, DB: db, Consumer: consumer}, nil
}

// WireNotifier builds notifier scan dependencies.
func WireNotifier(ctx context.Context, settings config.Settings, logger *slog.Logger) (*appnotifications.ScanUseCase, *persistence.DB, func(), error) {
	if logger == nil {
		logger = slog.Default()
	}
	tinvest.SetLogger(logger.With("component", "tinvest"))
	dsn := NormalizeDSN(settings.DatabaseURL)
	db, err := persistence.Open(dsn)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("open db: %w", err)
	}
	if err := db.Ping(ctx); err != nil {
		_ = db.Close()
		return nil, nil, nil, fmt.Errorf("ping db: %w", err)
	}
	if err := runMigrations(ctx, db); err != nil {
		_ = db.Close()
		return nil, nil, nil, fmt.Errorf("migrate: %w", err)
	}

	portfolioRepo := persistence.NewPortfolioRepository(db)
	notificationsRepo := persistence.NewNotificationsRepository(db)
	spreadRepo := persistence.NewSpreadSnapshotsRepository(db.DB)
	radarRepo := persistence.NewMarketRadarRepository(db.DB)
	tradingCtx := apptrading.NewContext(portfolioRepo, settings.TTradingTokenSandbox, settings.TTradingTokenProduction)
	bondSvc := appbonds.NewService(
		settings.KeyRate,
		settings.TaxRateFraction(),
		settings.TinkoffToken,
	)

	ledger := notifications.NewLedgerRepository(settings.NotifierLedgerPath)
	var bus *notifications.RedisBus
	if settings.RedisURL != "" {
		bus = notifications.NewRedisBus(settings.RedisURL)
		if ok, err := bus.Ping(ctx); err != nil || !ok {
			logger.Warn("Redis unavailable, falling back to direct DB writes", "error", err)
			bus = nil
		}
	}
	telegram := notifications.NewTelegramClient(settings.TelegramBotToken, settings.TelegramNotifyUserID)
	deliver := appnotifications.NewDeliverUseCase(ledger, bus, telegram, notificationsRepo)
	radarScan := appmarketsignals.NewScanRadarUseCase(
		bondSvc, spreadRepo, radarRepo, settings.KeyRate, settings.TaxRateFraction(),
	)
	scanner := appnotifications.NewScanUseCase(
		tradingCtx, bondSvc, deliver, spreadRepo, radarScan, logger, settings.NotificationsDev,
		settings.KeyRate, settings.TaxRateFraction(),
	)
	cleanup := func() { _ = db.Close() }
	return scanner, db, cleanup, nil
}

type noopConsumer struct{}

func (noopConsumer) Start(context.Context) error { return nil }
func (noopConsumer) Stop(context.Context) error  { return nil }
