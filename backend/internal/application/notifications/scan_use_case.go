package notifications

import (
	"context"
	"log/slog"
	"time"

	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	apptrading "github.com/tonatos/bond-monitor/backend/internal/application/trading"
	devnotify "github.com/tonatos/bond-monitor/backend/internal/dev/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// ScanUseCase scans trading portfolios and delivers alerts.
type ScanUseCase struct {
	tradingCtx       *apptrading.Context
	bondSvc          *appbonds.Service
	deliver          *DeliverUseCase
	logger           *slog.Logger
	notificationsDev bool
}

func NewScanUseCase(tradingCtx *apptrading.Context, bondSvc *appbonds.Service, deliver *DeliverUseCase, logger *slog.Logger, notificationsDev bool) *ScanUseCase {
	return &ScanUseCase{
		tradingCtx: tradingCtx, bondSvc: bondSvc, deliver: deliver, logger: logger,
		notificationsDev: notificationsDev,
	}
}

func (s *ScanUseCase) Run(ctx context.Context, today time.Time) (int, error) {
	portfolios, err := s.tradingCtx.Repo().ListAll(ctx)
	if err != nil {
		return 0, err
	}
	delivered := 0
	names := map[string]string{}
	for _, p := range portfolios {
		if p.Mode != domainPortfolio.PortfolioModeTrading || p.AccountID == nil || p.AccountKind == nil {
			continue
		}
		count, err := s.scanPortfolio(ctx, p, today, names)
		if err != nil {
			if s.logger != nil {
				s.logger.Warn("portfolio scan failed", "portfolio_id", p.ID, "error", err)
			}
			continue
		}
		delivered += count
	}
	_ = s.deliver.RetryPending(ctx, names)
	return delivered, nil
}

func (s *ScanUseCase) scanPortfolio(ctx context.Context, p domainPortfolio.Portfolio, today time.Time, names map[string]string) (int, error) {
	names[p.ID] = p.Name
	kind := *p.AccountKind
	accountID := *p.AccountID
	token, err := s.tradingCtx.Token(kind)
	if err != nil {
		return 0, err
	}
	client := tinvest.NewSDKClient(token, kind)
	snapshot, err := client.GetAccountSnapshot(kind, accountID)
	if err != nil {
		return 0, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	bondLots := 0
	for _, pos := range brokerSnapshot.BondPositions {
		if pos.Lots > 0 {
			bondLots++
		}
	}
	if bondLots == 0 {
		return 0, nil
	}
	universeLookup := s.bondSvc.LoadUniverse().Bonds
	holdingISINs := trading.HoldingISINsFromSnapshot(brokerSnapshot, universeLookup)
	if len(holdingISINs) == 0 {
		return 0, nil
	}
	isinList := make([]string, 0, len(holdingISINs))
	for isin := range holdingISINs {
		isinList = append(isinList, isin)
	}
	universe := s.bondSvc.LoadByISINs(isinList, domainPortfolio.DurationPolicyForPortfolio(p, domainPortfolio.RateScenarioHold), p.RiskProfile)
	universeByISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, bond := range universe {
		universeByISIN[bond.ISIN] = bond
	}
	if domainPortfolio.SyncRiskBaselines(p.RiskBaselines, holdingISINs, universeByISIN) {
		p.Touch()
		_, _ = s.tradingCtx.Repo().Save(ctx, p)
	}
	holdings := trading.BuildHoldings(brokerSnapshot, universe)
	positions := trading.EffectiveTradingPositions(p, brokerSnapshot, universe, today)
	if s.notificationsDev {
		devnotify.ApplyDevNotificationOverrides(&p, universe, positions, p.ID, devnotify.DevOverridesPath(), today)
	}
	holdingSnapshots := make([]domain.HoldingSnapshot, 0, len(holdings))
	for _, h := range holdings {
		holdingSnapshots = append(holdingSnapshots, domain.HoldingSnapshot{
			ISIN: h.ISIN, FIGI: h.FIGI, Name: h.Name, Lots: h.Lots, CurrentPricePct: h.CurrentPricePct,
		})
	}
	alerts := domain.CollectAlerts(domain.AlertParams{
		Portfolio: p, Holdings: holdingSnapshots, Positions: positions, Universe: universe,
		Today: today, Rules: domain.WorkerAlertRules,
		NotificationPolicy: domain.DefaultNotificationPolicy,
		RiskPolicy:         domainPortfolio.DefaultRiskMonitorPolicy,
	})
	for _, alert := range alerts {
		if err := s.deliver.ProcessAlert(ctx, alert, p.Name); err != nil {
			return len(alerts), err
		}
	}
	return len(alerts), nil
}
