package notifications

import (
	"fmt"
	"strings"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/market_signals"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

// HoldingSnapshot is a minimal holding view for alert rules.
type HoldingSnapshot struct {
	ISIN              string
	FIGI              string
	Name              string
	Lots              int
	CurrentPricePct   *float64
}

// AlertContext carries inputs for alert rule evaluation.
type AlertContext struct {
	Portfolio           portfolio.Portfolio
	Holdings            []HoldingSnapshot
	Positions           []portfolio.PortfolioPosition
	Universe            []bonds.BondRecord
	Today               time.Time
	KeyRatePP           float64
	TaxRateFraction     float64
	NotificationPolicy  NotificationPolicy
	RiskPolicy          portfolio.RiskMonitorPolicy
}

func (ctx AlertContext) universeByISIN() map[string]bonds.BondRecord {
	m := make(map[string]bonds.BondRecord, len(ctx.Universe))
	for _, bond := range ctx.Universe {
		m[bond.ISIN] = bond
	}
	return m
}

// AlertRule evaluates one class of portfolio alerts.
type AlertRule interface {
	Evaluate(ctx AlertContext) []Alert
}

type PutOfferActionRule struct{}

func (PutOfferActionRule) Evaluate(ctx AlertContext) []Alert {
	var alerts []Alert
	for _, position := range ctx.Positions {
		view := bonds.BondOfferViewFrom(position, ctx.Today)
		if view == nil || !portfolio.PutOfferSubmitDue(position, ctx.Today) {
			continue
		}
		daysUntil := shared.DaysBetween(ctx.Today, view.ExecutionDate)
		if view.SubmissionEnd != nil {
			daysUntil = shared.DaysBetween(ctx.Today, *view.SubmissionEnd)
		}
		urgency := AlertUrgencySoon
		if daysUntil <= 7 {
			urgency = AlertUrgencyCritical
		}
		detailKey := shared.FormatISODate(view.ExecutionDate)
		if view.SubmissionEnd != nil {
			detailKey = shared.FormatISODate(*view.SubmissionEnd)
		}
		template := fmt.Sprintf(
			"Здравствуйте! Прошу принять к исполнению заявку на досрочное погашение облигаций %s (ISIN %s) по пут-оферте.",
			position.Name, position.ISIN,
		)
		due := view.ExecutionDate
		if view.SubmissionEnd != nil {
			due = *view.SubmissionEnd
		}
		windowStatus := string(view.WindowStatus)
		alerts = append(alerts, Alert{
			PortfolioID: ctx.Portfolio.ID, Kind: AlertKindPutOfferAction,
			ISIN: position.ISIN, Name: position.Name, Lots: position.Lots, FIGI: position.FIGI,
			Reason: bonds.PutOfferActionMessage(*view), Urgency: urgency, DetailKey: detailKey,
			DueDate: &due, ChatTemplate: &template, SuggestedPricePct: position.OfferPricePct,
			OfferWindowStatus: &windowStatus,
			SubmissionStart: view.SubmissionStart, SubmissionEnd: view.SubmissionEnd,
		})
	}
	return alerts
}

type PutOfferWatchRule struct{}

func (PutOfferWatchRule) Evaluate(ctx AlertContext) []Alert {
	if !ctx.NotificationPolicy.IncludePutOfferWatchInAlerts {
		return nil
	}
	var alerts []Alert
	for _, position := range ctx.Positions {
		view := bonds.BondOfferViewFrom(position, ctx.Today)
		if view == nil || !portfolio.PutOfferAwarenessDue(position, ctx.Today) {
			continue
		}
		if portfolio.PutOfferSubmitDue(position, ctx.Today) {
			continue
		}
		windowStatus := string(view.WindowStatus)
		alerts = append(alerts, Alert{
			PortfolioID: ctx.Portfolio.ID, Kind: AlertKindPutOfferWatch,
			ISIN: position.ISIN, Name: position.Name, Lots: position.Lots, FIGI: position.FIGI,
			Reason: bonds.PutOfferAwarenessMessage(*view), Urgency: AlertUrgencyNormal,
			DetailKey: shared.FormatISODate(view.ExecutionDate), DueDate: &view.ExecutionDate,
			OfferWindowStatus: &windowStatus,
			SubmissionStart: view.SubmissionStart, SubmissionEnd: view.SubmissionEnd,
			SuggestedPricePct: position.OfferPricePct,
		})
	}
	return alerts
}

type RiskEscalationRule struct{}

func (RiskEscalationRule) Evaluate(ctx AlertContext) []Alert {
	universeByISIN := ctx.universeByISIN()
	var alerts []Alert
	for _, holding := range ctx.Holdings {
		if holding.ISIN == "" || holding.Lots <= 0 {
			continue
		}
		baseline, ok := ctx.Portfolio.RiskBaselines[holding.ISIN]
		if !ok {
			continue
		}
		bond, ok := universeByISIN[holding.ISIN]
		if !ok {
			continue
		}
		current := portfolio.RiskSnapshotFromBond(bond)
		escalations := portfolio.DetectRiskEscalations(baseline, current, ctx.RiskPolicy)
		if len(escalations) == 0 {
			continue
		}
		urgency := AlertUrgencySoon
		for _, e := range escalations {
			if e.Urgency == "critical" {
				urgency = AlertUrgencyCritical
				break
			}
		}
		var reasons []string
		var kinds []string
		for _, e := range escalations {
			reasons = append(reasons, e.Reason)
			kinds = append(kinds, string(e.Kind))
		}
		marketPrice := portfolio.ReferenceMarketPricePct(bond.LastPrice, holding.CurrentPricePct, 100)
		buffer := portfolio.SellLimitPriceBuffer(ctx.Portfolio.AccountKind)
		suggested := float64(portfolio.SuggestedSellLimitPricePct(marketPrice, buffer))
		reason := "Ухудшение риск-профиля эмитента: " + strings.Join(reasons, "; ") + ". Рекомендуем продать."
		alerts = append(alerts, Alert{
			PortfolioID: ctx.Portfolio.ID, Kind: AlertKindRiskEscalation,
			ISIN: holding.ISIN, Name: holding.Name, Lots: holding.Lots, FIGI: strPtr(holding.FIGI),
			Reason: reason, Urgency: urgency, DetailKey: kinds[0],
			SuggestedPricePct: &suggested, MarketPricePct: &marketPrice,
			RiskAcknowledgeable: true, EscalationKinds: kinds,
		})
	}
	return alerts
}

type SpreadAnomalyRule struct {
	Policy market_signals.SpreadAnomalyPolicy
}

func (r SpreadAnomalyRule) Evaluate(ctx AlertContext) []Alert {
	policy := r.Policy
	if policy.MinPeers == 0 {
		policy = market_signals.DefaultSpreadAnomalyPolicy
	}
	universeByISIN := ctx.universeByISIN()
	var alerts []Alert

	for _, holding := range ctx.Holdings {
		if holding.ISIN == "" || holding.Lots <= 0 {
			continue
		}
		bond, ok := universeByISIN[holding.ISIN]
		if !ok {
			continue
		}
		if bond.Sector == "" {
			continue
		}
		targetSpread := market_signals.CreditSpreadPP(bond, ctx.KeyRatePP, ctx.TaxRateFraction)
		if targetSpread == nil {
			continue
		}
		peers := market_signals.PeerGroup(bond, ctx.Universe, policy)
		if len(peers) < policy.MinPeers {
			continue
		}
		spreads := make([]float64, 0, len(peers))
		for _, p := range peers {
			if s := market_signals.CreditSpreadPP(p, ctx.KeyRatePP, ctx.TaxRateFraction); s != nil {
				spreads = append(spreads, *s)
			}
		}
		stats := market_signals.SpreadStatsFromPeers(spreads)
		if stats == nil || stats.Peers < policy.MinPeers {
			continue
		}
		anomaly := *targetSpread - stats.ExpectedPP
		z := market_signals.ZScore(*targetSpread, stats.ExpectedPP, stats.StdDevPP)
		isAnomaly := anomaly >= policy.MinAnomalyPP
		if z != nil && *z >= policy.MinZScore {
			isAnomaly = true
		}
		if !isAnomaly {
			continue
		}
		alerts = append(alerts, Alert{
			PortfolioID: ctx.Portfolio.ID, Kind: AlertKindSpreadAnomaly,
			ISIN: holding.ISIN, Name: holding.Name, Lots: holding.Lots, FIGI: strPtr(holding.FIGI),
			Reason: fmt.Sprintf(
				"Кредитный спред расширился относительно похожих бумаг: %.1f п.п. vs медиана %.1f п.п. (Δ %.1f п.п., peers %d).",
				*targetSpread, stats.ExpectedPP, anomaly, stats.Peers,
			),
			Urgency:   AlertUrgencyNormal,
			DetailKey: bond.Sector,
		})
	}
	return alerts
}

type SectorConcentrationRule struct {
	MaxSectorShare float64
}

func (r SectorConcentrationRule) Evaluate(ctx AlertContext) []Alert {
	universeByISIN := ctx.universeByISIN()
	maxShare := r.MaxSectorShare
	if maxShare <= 0 {
		maxShare = portfolio.DefaultDiversificationPolicy.MaxSectorShare
	}

	lotsByISIN := make(map[string]int)
	if len(ctx.Holdings) > 0 {
		for _, h := range ctx.Holdings {
			if h.ISIN != "" && h.Lots > 0 {
				lotsByISIN[h.ISIN] += h.Lots
			}
		}
	} else {
		for _, p := range ctx.Positions {
			if p.ISIN != "" && p.Lots > 0 {
				lotsByISIN[p.ISIN] += p.Lots
			}
		}
	}

	totalValue := 0.0
	for isin, lots := range lotsByISIN {
		b, ok := universeByISIN[isin]
		if !ok {
			continue
		}
		if p := b.PricePerLotRub(); p != nil && *p > 0 {
			totalValue += *p * float64(lots)
		}
	}
	if totalValue <= 0 {
		return nil
	}
	exposures := portfolio.ExposureBySector(universeByISIN, lotsByISIN, totalValue)
	for _, e := range exposures {
		if e.Key == "unknown" {
			continue
		}
		if e.Share <= maxShare {
			continue
		}
		sectorLabel := e.Key
		sharePct := e.Share * 100
		alerts := []Alert{{
			PortfolioID: ctx.Portfolio.ID,
			Kind:        AlertKindSectorConcentration,
			ISIN:        "sector:" + e.Key,
			Name:        "Концентрация в секторе: " + sectorLabel,
			Lots:        0,
			Reason: fmt.Sprintf(
				"Сектор «%s» занимает %.1f%% портфеля (лимит %.0f%%). Рекомендуем диверсифицировать.",
				sectorLabel, sharePct, maxShare*100,
			),
			Urgency:   AlertUrgencyNormal,
			DetailKey: e.Key,
		}}
		return alerts
	}
	return nil
}

func strPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

var DefaultAlertRules = []AlertRule{
	PutOfferActionRule{},
	PutOfferWatchRule{},
	RiskEscalationRule{},
	SectorConcentrationRule{},
	SpreadAnomalyRule{},
}

var WorkerAlertRules = []AlertRule{
	PutOfferActionRule{},
	RiskEscalationRule{},
	SectorConcentrationRule{},
	SpreadAnomalyRule{},
}

// AlertParams groups inputs for CollectAlerts.
type AlertParams struct {
	Portfolio          portfolio.Portfolio
	Holdings           []HoldingSnapshot
	Positions          []portfolio.PortfolioPosition
	Universe           []bonds.BondRecord
	Today              time.Time
	KeyRatePP          float64
	TaxRateFraction    float64
	Rules              []AlertRule
	NotificationPolicy NotificationPolicy
	RiskPolicy         portfolio.RiskMonitorPolicy
}

// CollectAlerts runs alert rules and returns detected events.
func CollectAlerts(params AlertParams) []Alert {
	ctx := AlertContext{
		Portfolio: params.Portfolio, Holdings: params.Holdings, Positions: params.Positions,
		Universe: params.Universe, Today: params.Today,
		KeyRatePP: params.KeyRatePP, TaxRateFraction: params.TaxRateFraction,
		NotificationPolicy: params.NotificationPolicy, RiskPolicy: params.RiskPolicy,
	}
	rules := params.Rules
	if len(rules) == 0 {
		rules = DefaultAlertRules
	}
	var alerts []Alert
	for _, rule := range rules {
		alerts = append(alerts, rule.Evaluate(ctx)...)
	}
	return alerts
}
