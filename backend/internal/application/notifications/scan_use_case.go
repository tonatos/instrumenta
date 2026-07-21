package notifications

import (
	"context"
	"log/slog"
	"sort"
	"time"

	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	appmarketsignals "github.com/tonatos/bond-monitor/backend/internal/application/market_signals"
	apptrading "github.com/tonatos/bond-monitor/backend/internal/application/trading"
	devnotify "github.com/tonatos/bond-monitor/backend/internal/dev/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/market_signals"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// ScanUseCase scans trading portfolios and delivers alerts.
type ScanUseCase struct {
	tradingCtx       *apptrading.Context
	bondSvc          *appbonds.Service
	deliver          *DeliverUseCase
	snapshots        *persistence.SpreadSnapshotsRepository
	radarScan        *appmarketsignals.ScanRadarUseCase
	logger           *slog.Logger
	notificationsDev bool
	keyRatePP        float64
	taxRateFraction  float64
}

func NewScanUseCase(tradingCtx *apptrading.Context, bondSvc *appbonds.Service, deliver *DeliverUseCase, snapshots *persistence.SpreadSnapshotsRepository, radarScan *appmarketsignals.ScanRadarUseCase, logger *slog.Logger, notificationsDev bool, keyRatePP, taxRateFraction float64) *ScanUseCase {
	return &ScanUseCase{
		tradingCtx: tradingCtx, bondSvc: bondSvc, deliver: deliver, logger: logger,
		snapshots:        snapshots,
		radarScan:        radarScan,
		notificationsDev: notificationsDev,
		keyRatePP:        keyRatePP,
		taxRateFraction:  taxRateFraction,
	}
}

func (s *ScanUseCase) Run(ctx context.Context, today time.Time) (int, error) {
	portfolios, err := s.tradingCtx.Repo().ListAll(ctx)
	if err != nil {
		return 0, err
	}
	delivered := 0
	names := map[string]string{}
	owners := map[string]int64{}
	for _, p := range portfolios {
		if p.Mode != domainPortfolio.PortfolioModeTrading || p.AccountID == nil || p.AccountKind == nil {
			continue
		}
		owners[p.ID] = p.OwnerTelegramID
		count, err := s.scanPortfolio(ctx, p, today, names)
		if err != nil {
			if s.logger != nil {
				s.logger.Warn("portfolio scan failed", "portfolio_id", p.ID, "error", err)
			}
			continue
		}
		delivered += count
	}
	_ = s.deliver.RetryPending(ctx, names, owners)
	if s.radarScan != nil {
		if err := s.radarScan.Run(ctx, today); err != nil && s.logger != nil {
			s.logger.Warn("market radar scan failed", "error", err)
		}
	}
	return delivered, nil
}

func (s *ScanUseCase) scanPortfolio(ctx context.Context, p domainPortfolio.Portfolio, today time.Time, names map[string]string) (int, error) {
	names[p.ID] = p.Name
	kind := *p.AccountKind
	accountID := *p.AccountID
	token, err := s.tradingCtx.TokenFor(ctx, p.OwnerTelegramID, kind)
	if err != nil {
		if s.logger != nil {
			s.logger.Warn("skip portfolio: no broker credentials", "portfolio_id", p.ID, "owner", p.OwnerTelegramID, "error", err)
		}
		return 0, nil
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
	universeAll := s.bondSvc.LoadUniverse().Bonds
	universeAllByISIN := make(map[string]bonds.BondRecord, len(universeAll))
	for _, b := range universeAll {
		universeAllByISIN[b.ISIN] = b
	}
	holdingISINs := trading.HoldingISINsFromSnapshot(brokerSnapshot, universeAll)
	if len(holdingISINs) == 0 {
		return 0, nil
	}
	peerPolicy := market_signals.DefaultSpreadAnomalyPolicy
	isinSet := make(map[string]struct{}, len(holdingISINs))
	for isin := range holdingISINs {
		isinSet[isin] = struct{}{}
		if b, ok := universeAllByISIN[isin]; ok {
			for _, peer := range market_signals.PeerGroup(b, universeAll, peerPolicy) {
				isinSet[peer.ISIN] = struct{}{}
			}
		}
	}
	isinList := make([]string, 0, len(isinSet))
	for isin := range isinSet {
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

	var temporalAlerts []domain.Alert
	if s.snapshots != nil {
		dateKey := persistence.DateKey(today)
		pastKey := persistence.DateKey(today.AddDate(0, 0, -7))

		// (1) Write today's snapshots (holdings + peers).
		for _, bond := range universe {
			spread := market_signals.CreditSpreadPP(bond, s.keyRatePP, s.taxRateFraction)
			if spread == nil {
				continue
			}
			var ord *int
			if bond.CreditRating != nil {
				if v, ok := bonds.RatingOrder[*bond.CreditRating]; ok {
					ord = &v
				}
			}
			_ = s.snapshots.Upsert(ctx, persistence.SpreadSnapshot{
				ISIN:           bond.ISIN,
				Date:           dateKey,
				CreditSpreadPP: *spread,
				LastPricePct:   bond.LastPrice,
				Sector:         bond.Sector,
				RatingOrdinal:  ord,
			})
		}

		// (2) Load snapshots from 7 days ago for the same universe subset.
		past, _ := s.snapshots.ListByISINsAndDate(ctx, isinList, pastKey)
		now, _ := s.snapshots.ListByISINsAndDate(ctx, isinList, dateKey)

		// Market baseline: median price change across all peer bonds (dedup).
		var marketChanges []float64
		for isin, cur := range now {
			prev, ok := past[isin]
			if !ok || cur.LastPricePct == nil || prev.LastPricePct == nil || *prev.LastPricePct <= 0 {
				continue
			}
			marketChanges = append(marketChanges, (*cur.LastPricePct-*prev.LastPricePct)/(*prev.LastPricePct))
		}
		marketMedian := median(marketChanges)

		for _, h := range holdings {
			if h.ISIN == "" || h.Lots <= 0 {
				continue
			}
			bond, ok := universeByISIN[h.ISIN]
			if !ok || bond.Sector == "" {
				continue
			}
			cur, okNow := now[h.ISIN]
			prev, okPrev := past[h.ISIN]
			if !okNow || !okPrev || cur.LastPricePct == nil || prev.LastPricePct == nil || *prev.LastPricePct <= 0 {
				continue
			}
			bondChange := (*cur.LastPricePct - *prev.LastPricePct) / (*prev.LastPricePct)

			peers := market_signals.PeerGroup(bond, universe, peerPolicy)
			var sectorChanges []float64
			var peerSpreadChanges []float64
			for _, peer := range peers {
				curPeer, okNowPeer := now[peer.ISIN]
				prevPeer, okPrevPeer := past[peer.ISIN]
				if okNowPeer && okPrevPeer && curPeer.LastPricePct != nil && prevPeer.LastPricePct != nil && *prevPeer.LastPricePct > 0 {
					sectorChanges = append(sectorChanges, (*curPeer.LastPricePct-*prevPeer.LastPricePct)/(*prevPeer.LastPricePct))
				}
				if okNowPeer && okPrevPeer {
					peerSpreadChanges = append(peerSpreadChanges, curPeer.CreditSpreadPP-prevPeer.CreditSpreadPP)
				}
			}
			sectorMedian := median(sectorChanges)
			attr := market_signals.BuildAttribution(bondChange*100, sectorMedian*100, marketMedian*100)

			// Sector stress attribution (v1): sector падает, а бумага примерно вместе с сектором.
			if attr.Interpretation == "sector_stress" {
				temporalAlerts = append(temporalAlerts, domain.Alert{
					PortfolioID: p.ID, Kind: domain.AlertKindSectorStress,
					ISIN: h.ISIN, Name: h.Name, Lots: h.Lots, FIGI: bonds.StrPtr(h.FIGI),
					Reason: "Похоже на секторное давление: бумага падает вместе с похожими бумагами из сектора.",
					Urgency: domain.AlertUrgencyNormal,
					DetailKey: bond.Sector,
					ExtraPayload: map[string]any{
						"kind":                  "sector_stress",
						"bond_change_7d_pct":       attr.BondChange7dPct,
						"sector_change_7d_pct":     attr.SectorChange7dPct,
						"market_change_7d_pct":     attr.MarketChange7dPct,
						"idiosyncratic_excess_pct": attr.IdiosyncraticExcess7dPct,
					},
				})
			}

			// Temporal spread widening vs peers.
			if okNow && okPrev {
				spreadChange := cur.CreditSpreadPP - prev.CreditSpreadPP
				peerMedian := median(peerSpreadChanges)
				if spreadChange-peerMedian >= 5.0 {
					temporalAlerts = append(temporalAlerts, domain.Alert{
						PortfolioID: p.ID, Kind: domain.AlertKindSpreadWidening,
						ISIN: h.ISIN, Name: h.Name, Lots: h.Lots, FIGI: bonds.StrPtr(h.FIGI),
						Reason: "Кредитный спред расширился сильнее, чем у похожих бумаг за последнюю неделю.",
						Urgency: domain.AlertUrgencyNormal,
						DetailKey: bond.Sector,
						ExtraPayload: map[string]any{
							"kind":                 "spread_widening",
							"spread_change_7d_pp":  spreadChange,
							"peer_change_7d_pp":    peerMedian,
							"bond_change_7d_pct":   attr.BondChange7dPct,
							"sector_change_7d_pct": attr.SectorChange7dPct,
						},
					})
				}
			}

			// Turbo-entry (opt-in): tactical buy on sector panic.
			if p.TurboEntryEnabled &&
				attr.SectorChange7dPct < -15 &&
				attr.BondChange7dPct < attr.SectorChange7dPct-5 {
				if base, ok := p.RiskBaselines[h.ISIN]; ok {
					current := domainPortfolio.RiskSnapshotFromBond(bond)
					if len(domainPortfolio.DetectRiskEscalations(base, current, domainPortfolio.DefaultRiskMonitorPolicy)) == 0 {
						if len(domainPortfolio.RiskProfileFilter([]bonds.BondRecord{bond}, p.RiskProfile)) == 1 {
							marketPrice := domainPortfolio.ReferenceMarketPricePct(bond.LastPrice, h.CurrentPricePct, 100)
							buffer := domainPortfolio.BuyLimitPriceBuffer(p.AccountKind)
							suggested := float64(domainPortfolio.SuggestedBuyLimitPricePct(marketPrice, buffer))
							temporalAlerts = append(temporalAlerts, domain.Alert{
								PortfolioID: p.ID, Kind: domain.AlertKindTurboEntry,
								ISIN: h.ISIN, Name: h.Name, Lots: 1, FIGI: bonds.StrPtr(h.FIGI),
								Reason: "Turbo-entry: сектор в панике, а бумага просела сильнее сектора без ухудшения рейтинга. Тактическая докупка (экспериментально).",
								Urgency: domain.AlertUrgencyNormal,
								DetailKey: bond.Sector,
								SuggestedPricePct: &suggested,
								MarketPricePct: &marketPrice,
								ExtraPayload: map[string]any{
									"kind":                  "turbo_entry",
									"bond_change_7d_pct":    attr.BondChange7dPct,
									"sector_change_7d_pct":  attr.SectorChange7dPct,
									"market_change_7d_pct":  attr.MarketChange7dPct,
									"idiosyncratic_excess_pct": attr.IdiosyncraticExcess7dPct,
								},
							})
						}
					}
				}
			}
		}
	}

	alerts := domain.CollectAlerts(domain.AlertParams{
		Portfolio: p, Holdings: holdingSnapshots, Positions: positions, Universe: universe,
		Today: today, Rules: domain.WorkerAlertRules,
		KeyRatePP: s.keyRatePP, TaxRateFraction: s.taxRateFraction,
		NotificationPolicy: domain.DefaultNotificationPolicy,
		RiskPolicy:         domainPortfolio.DefaultRiskMonitorPolicy,
	})
	alerts = append(alerts, temporalAlerts...)
	for _, alert := range alerts {
		if err := s.deliver.ProcessAlert(ctx, alert, p.Name, p.OwnerTelegramID); err != nil {
			return len(alerts), err
		}
	}
	return len(alerts), nil
}

func median(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	cp := append([]float64(nil), values...)
	sort.Float64s(cp)
	if len(cp)%2 == 1 {
		return cp[len(cp)/2]
	}
	return (cp[len(cp)/2-1] + cp[len(cp)/2]) / 2
}
