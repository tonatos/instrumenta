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
	appbilling "github.com/tonatos/bond-monitor/backend/internal/application/billing"
	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	appmarketsignals "github.com/tonatos/bond-monitor/backend/internal/application/market_signals"
	appnotifications "github.com/tonatos/bond-monitor/backend/internal/application/notifications"
	appportfolio "github.com/tonatos/bond-monitor/backend/internal/application/portfolio"
	apptrading "github.com/tonatos/bond-monitor/backend/internal/application/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/crypto"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/moex"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/ratings"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/yookassa"
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

func buildTokenSource(settings config.Settings, credRepo *persistence.BrokerCredentialsRepository) *apptrading.CredentialTokenSource {
	return &apptrading.CredentialTokenSource{
		Repo:               credRepo,
		SandboxEnvToken:    settings.TTradingTokenSandbox,
		ProductionEnvToken: settings.TTradingTokenProduction,
		AllowEnvFallback:   !settings.AuthEnabled(),
	}
}

func buildCredentialRepo(settings config.Settings, db *persistence.DB) (*persistence.BrokerCredentialsRepository, error) {
	kekRaw := settings.BrokerKEK
	if kekRaw == "" {
		if settings.AuthEnabled() {
			return nil, fmt.Errorf("BROKER_KEK is required when auth is enabled")
		}
		kekRaw = settings.AuthSecret
		if kekRaw == "" {
			kekRaw = "insecure-dev-broker-kek"
		}
	}
	wrapper, err := crypto.NewLocalKEK(kekRaw, 1)
	if err != nil {
		return nil, fmt.Errorf("broker kek: %w", err)
	}
	return persistence.NewBrokerCredentialsRepository(db, wrapper), nil
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

	credRepo, err := buildCredentialRepo(settings, db)
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	tokens := buildTokenSource(settings, credRepo)

	portfolioRepo := persistence.NewPortfolioRepository(db)
	favoritesRepo := persistence.NewFavoritesRepository(db)
	usersRepo := persistence.NewUserRepository(db)
	notificationsRepo := persistence.NewNotificationsRepository(db)
	deployRepo := persistence.NewDeploySessionRepository(db)
	radarRepo := persistence.NewMarketRadarRepository(db.DB)

	bondRefRepo := persistence.NewBondReferenceRepository(db.DB)
	ratingsLoader := ratings.NewLoader(bondRefRepo)
	defaultFlags := moex.NewDefaultFlagsService(bondRefRepo)

	bondInner := appbonds.NewServiceWithDeps(
		settings.KeyRate,
		settings.TaxRateFraction(),
		settings.TinkoffToken,
		moex.NewClient(),
		ratingsLoader,
		tinvest.NewReadClient(settings.TinkoffToken),
		defaultFlags,
	)
	if logger != nil {
		logger.Info("warming bond universe cache")
	}
	universe := bondInner.LoadUniverse()
	logger.Info("bond cache ready", "universe", len(universe.Bonds))
	tradingInner := apptrading.NewService(
		portfolioRepo,
		deployRepo,
		notificationsRepo,
		tokens,
	)
	portfolioInner := appportfolio.NewService(portfolioRepo, tradingInner.PlanUseCase())

	jwtManager := auth.NewJWTManager(settings.AuthSecret, settings.AuthEnabled()).
		WithDevUser(settings.DevTelegramID, "Dev User")
	var consumer application.NotificationConsumer
	if settings.RedisURL != "" {
		consumer = appnotifications.NewConsumer(settings.RedisURL, notificationsRepo, logger)
	} else {
		consumer = noopConsumer{}
	}

	getRadar := appmarketsignals.NewGetRadarUseCase(radarRepo, portfolioInner)

	billingRepo := persistence.NewBillingRepository(db)
	yooGateway := yookassa.NewClient(settings.YooKassaShopID, settings.YooKassaSecretKey, &http.Client{Timeout: 20 * time.Second})
	billingSvc := appbilling.NewService(
		billingRepo,
		yooGateway,
		settings.ComplimentaryTelegramIDs,
		settings.YooKassaReturnURLResolved(),
	)

	botUsername := settings.TelegramBotUsername
	if botUsername == "" && settings.TelegramBotToken != "" {
		tg := notifications.NewTelegramClient(settings.TelegramBotToken)
		if me, err := tg.GetMe(ctx); err == nil {
			botUsername = me.Username
		} else {
			logger.Warn("telegram getMe failed; set TELEGRAM_BOT_USERNAME for deep links", "error", err)
		}
	}

	deps := httpapi.Deps{
		Settings:            settings,
		JWT:                 jwtManager,
		Bonds:               adapters.NewBondService(bondInner),
		Favorites:           adapters.NewFavoritesRepository(favoritesRepo),
		Portfolios:          adapters.NewPortfolioService(portfolioInner),
		Trading:             tradingInner,
		Notifications:       adapters.NewNotificationsRepository(notificationsRepo),
		MarketRadar:         adapters.NewMarketRadarService(getRadar),
		Credentials:         credRepo,
		Users:               usersRepo,
		TokenSource:         tokens,
		Billing:             billingSvc,
		TelegramBotUsername: botUsername,
		HTTPClient:          &http.Client{Timeout: 20 * time.Second},
	}

	return &App{Deps: deps, DB: db, Consumer: consumer}, nil
}

// WireNotifier builds notifier scan, billing renewal, and Telegram bot inbox.
func WireNotifier(ctx context.Context, settings config.Settings, logger *slog.Logger) (
	*appnotifications.ScanUseCase,
	*appbilling.Service,
	*appnotifications.BotInbox,
	*persistence.DB,
	func(),
	error,
) {
	if logger == nil {
		logger = slog.Default()
	}
	tinvest.SetLogger(logger.With("component", "tinvest"))
	dsn := NormalizeDSN(settings.DatabaseURL)
	db, err := persistence.Open(dsn)
	if err != nil {
		return nil, nil, nil, nil, nil, fmt.Errorf("open db: %w", err)
	}
	if err := db.Ping(ctx); err != nil {
		_ = db.Close()
		return nil, nil, nil, nil, nil, fmt.Errorf("ping db: %w", err)
	}
	if err := runMigrations(ctx, db); err != nil {
		_ = db.Close()
		return nil, nil, nil, nil, nil, fmt.Errorf("migrate: %w", err)
	}

	credRepo, err := buildCredentialRepo(settings, db)
	if err != nil {
		_ = db.Close()
		return nil, nil, nil, nil, nil, err
	}
	tokens := buildTokenSource(settings, credRepo)

	portfolioRepo := persistence.NewPortfolioRepository(db)
	usersRepo := persistence.NewUserRepository(db)
	notificationsRepo := persistence.NewNotificationsRepository(db)
	spreadRepo := persistence.NewSpreadSnapshotsRepository(db.DB)
	radarRepo := persistence.NewMarketRadarRepository(db.DB)
	bondRefRepo := persistence.NewBondReferenceRepository(db.DB)
	tradingCtx := apptrading.NewContext(portfolioRepo, tokens)
	bondSvc := appbonds.NewServiceWithDeps(
		settings.KeyRate,
		settings.TaxRateFraction(),
		settings.TinkoffToken,
		moex.NewClient(),
		ratings.NewLoader(bondRefRepo),
		tinvest.NewReadClient(settings.TinkoffToken),
		moex.NewDefaultFlagsService(bondRefRepo),
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
	billingRepo := persistence.NewBillingRepository(db)
	billingSvc := appbilling.NewService(
		billingRepo,
		yookassa.NewClient(settings.YooKassaShopID, settings.YooKassaSecretKey, &http.Client{Timeout: 20 * time.Second}),
		settings.ComplimentaryTelegramIDs,
		settings.YooKassaReturnURLResolved(),
	)
	telegram := notifications.NewTelegramClient(settings.TelegramBotToken)
	gate := &appnotifications.SubscriptionTelegramGate{Users: usersRepo, Billing: billingSvc}
	deliver := appnotifications.NewDeliverUseCase(ledger, bus, telegram, notificationsRepo, gate)
	radarScan := appmarketsignals.NewScanRadarUseCase(
		bondSvc, spreadRepo, radarRepo, settings.KeyRate, settings.TaxRateFraction(),
	)
	scanner := appnotifications.NewScanUseCase(
		tradingCtx, bondSvc, deliver, spreadRepo, radarScan, logger, settings.NotificationsDev,
		settings.KeyRate, settings.TaxRateFraction(),
	)
	inbox := appnotifications.NewBotInbox(telegram, usersRepo, billingSvc, logger)
	cleanup := func() { _ = db.Close() }
	return scanner, billingSvc, inbox, db, cleanup, nil
}

type noopConsumer struct{}

func (noopConsumer) Start(context.Context) error { return nil }
func (noopConsumer) Stop(context.Context) error  { return nil }
