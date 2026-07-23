package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/app"
	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	appmarket "github.com/tonatos/bond-monitor/backend/internal/application/market"
	apptrading "github.com/tonatos/bond-monitor/backend/internal/application/trading"
	devnotify "github.com/tonatos/bond-monitor/backend/internal/dev/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/domain/preferences"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/moex"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/ratings"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/config"
	applogging "github.com/tonatos/bond-monitor/backend/internal/interfaces/logging"
)

var simulateScenarios = map[string]func(portfolioID, isin string, today time.Time) map[string]any{
	"put-offer": devnotify.BuildPutOfferOverrides,
	"risk-default": func(portfolioID, isin string, _ time.Time) map[string]any {
		return devnotify.BuildRiskDefaultOverrides(portfolioID, isin)
	},
	"risk-downgrade": func(portfolioID, isin string, _ time.Time) map[string]any {
		return devnotify.BuildRiskDowngradeOverrides(portfolioID, isin)
	},
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "simulate":
		os.Exit(runSimulate(os.Args[2:]))
	case "scan":
		os.Exit(runScan())
	case "reset":
		os.Exit(runReset(os.Args[2:]))
	case "-h", "--help", "help":
		usage()
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `Usage:
  dev-notify simulate <put-offer|risk-default|risk-downgrade> --portfolio <id> [--isin <isin>]
  dev-notify scan
  dev-notify reset [--portfolio <id>]

Requires NOTIFICATIONS_DEV=true for simulate and scan.
`)
}

func requireNotificationsDev(settings config.Settings) bool {
	if settings.NotificationsDev {
		return true
	}
	fmt.Fprintln(os.Stderr, "NOTIFICATIONS_DEV is disabled. Set NOTIFICATIONS_DEV=true in .env.")
	return false
}

func runSimulate(args []string) int {
	settings := config.Load()
	if !requireNotificationsDev(settings) {
		return 1
	}
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "scenario required: put-offer, risk-default, risk-downgrade")
		return 1
	}
	scenario := args[0]
	builder, ok := simulateScenarios[scenario]
	if !ok {
		fmt.Fprintf(os.Stderr, "unknown scenario: %s\n", scenario)
		return 1
	}
	fs := newFlagSet("simulate " + scenario)
	portfolioID := fs.String("portfolio", "", "trading portfolio ID")
	isin := fs.String("isin", "", "held ISIN (default: first holding)")
	if err := fs.Parse(args[1:]); err != nil {
		return 1
	}
	if *portfolioID == "" {
		fmt.Fprintln(os.Stderr, "--portfolio is required")
		return 1
	}

	ctx := context.Background()
	resolvedISIN, err := resolveHoldingISIN(ctx, settings, *portfolioID, *isin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}

	today := time.Now()
	payload := builder(*portfolioID, resolvedISIN, today)
	path := devnotify.DevOverridesPath()
	if err := devnotify.SaveDevOverrides(path, payload); err != nil {
		fmt.Fprintf(os.Stderr, "save overrides: %v\n", err)
		return 1
	}
	fmt.Printf("Wrote %s overrides for %s → %s\n", scenario, resolvedISIN, path)
	return 0
}

func runScan() int {
	settings := config.Load()
	if !requireNotificationsDev(settings) {
		return 1
	}
	logger := applogging.New(settings.LogLevel, settings.Debug)
	ctx := context.Background()
	scanner, _, _, _, cleanup, err := app.WireNotifier(ctx, settings, logger)
	if err != nil {
		fmt.Fprintf(os.Stderr, "wire notifier: %v\n", err)
		return 1
	}
	defer cleanup()

	count, err := scanner.Run(ctx, time.Now())
	if err != nil {
		fmt.Fprintf(os.Stderr, "scan failed: %v\n", err)
		return 1
	}
	fmt.Printf("Scan complete, alerts processed=%d\n", count)
	return 0
}

func runReset(args []string) int {
	settings := config.Load()
	fs := newFlagSet("reset")
	portfolioID := fs.String("portfolio", "", "limit reset to one portfolio")
	if err := fs.Parse(args); err != nil {
		return 1
	}
	ledger := notifications.NewLedgerRepository(settings.NotifierLedgerPath)
	var deleted int
	var err error
	if *portfolioID != "" {
		deleted, err = ledger.DeleteForPortfolio(*portfolioID)
		if err != nil {
			fmt.Fprintf(os.Stderr, "reset failed: %v\n", err)
			return 1
		}
		fmt.Printf("Deleted %d ledger entries for portfolio %s\n", deleted, *portfolioID)
	} else {
		deleted, err = ledger.DeleteAll()
		if err != nil {
			fmt.Fprintf(os.Stderr, "reset failed: %v\n", err)
			return 1
		}
		fmt.Printf("Deleted %d ledger entries\n", deleted)
	}
	return 0
}

func resolveHoldingISIN(ctx context.Context, settings config.Settings, portfolioID, isin string) (string, error) {
	dsn := app.NormalizeDSN(settings.DatabaseURL)
	db, err := persistence.Open(dsn)
	if err != nil {
		return "", fmt.Errorf("open db: %w", err)
	}
	defer db.Close()

	tradingCtx := apptrading.NewContext(
		persistence.NewPortfolioRepository(db),
		&apptrading.CredentialTokenSource{
			SandboxEnvToken:    settings.TTradingTokenSandbox,
			ProductionEnvToken: settings.TTradingTokenProduction,
			AllowEnvFallback:   true,
		},
	)
	bondRefRepo := persistence.NewBondReferenceRepository(db.DB)
	bondSvc := appbonds.NewServiceWithDeps(
		appmarket.DefaultKeyRateFallback,
		preferences.TaxRateFraction(preferences.DefaultTaxRatePct),
		settings.TinkoffToken,
		moex.NewClient(),
		ratings.NewLoader(bondRefRepo),
		tinvest.NewReadClient(settings.TinkoffToken),
		moex.NewDefaultFlagsService(bondRefRepo),
	)

	ownerID := settings.DevTelegramID
	if ownerID == 0 {
		ownerID = 1
	}
	ctx = auth.WithOwnerTelegramID(ctx, ownerID)
	p, err := tradingCtx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return "", err
	}
	token, err := tradingCtx.TokenFor(ctx, p.OwnerTelegramID, *p.AccountKind)
	if err != nil {
		return "", err
	}
	client := tinvest.NewSDKClient(token, *p.AccountKind)
	snapshot, err := client.GetAccountSnapshot(*p.AccountKind, *p.AccountID)
	if err != nil {
		return "", err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)

	bondLots := 0
	for _, pos := range brokerSnapshot.BondPositions {
		if pos.Lots > 0 {
			bondLots++
		}
	}
	if bondLots == 0 {
		return "", fmt.Errorf(
			"portfolio %s has no holdings on the broker account; buy a bond in sandbox first",
			portfolioID,
		)
	}

	keyRate, taxRate := bondSvc.DefaultRates()
	universeLookup := bondSvc.LoadUniverse(keyRate, taxRate).Bonds
	holdingISINs := trading.HoldingISINsFromSnapshot(brokerSnapshot, universeLookup)
	if len(holdingISINs) == 0 {
		var figis []string
		for figi, pos := range brokerSnapshot.BondPositions {
			if pos.Lots > 0 {
				figis = append(figis, figi)
			}
		}
		sort.Strings(figis)
		return "", fmt.Errorf(
			"portfolio %s has %d bond position(s) on the account (FIGIs: %s), but ISIN mapping failed; check TINKOFF_TOKEN and bond universe cache",
			portfolioID, bondLots, strings.Join(figis, ", "),
		)
	}
	sorted := make([]string, 0, len(holdingISINs))
	for held := range holdingISINs {
		sorted = append(sorted, held)
	}
	sort.Strings(sorted)

	if isin != "" {
		if _, ok := holdingISINs[isin]; !ok {
			return "", fmt.Errorf("ISIN %s is not held on account; holdings: %s", isin, strings.Join(sorted, ", "))
		}
		return isin, nil
	}
	return sorted[0], nil
}

func newFlagSet(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}
