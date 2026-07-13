package notifications

import (
	"fmt"
	"strings"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
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
}

var WorkerAlertRules = []AlertRule{
	PutOfferActionRule{},
	RiskEscalationRule{},
}

// AlertParams groups inputs for CollectAlerts.
type AlertParams struct {
	Portfolio          portfolio.Portfolio
	Holdings           []HoldingSnapshot
	Positions          []portfolio.PortfolioPosition
	Universe           []bonds.BondRecord
	Today              time.Time
	Rules              []AlertRule
	NotificationPolicy NotificationPolicy
	RiskPolicy         portfolio.RiskMonitorPolicy
}

// CollectAlerts runs alert rules and returns detected events.
func CollectAlerts(params AlertParams) []Alert {
	ctx := AlertContext{
		Portfolio: params.Portfolio, Holdings: params.Holdings, Positions: params.Positions,
		Universe: params.Universe, Today: params.Today,
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
