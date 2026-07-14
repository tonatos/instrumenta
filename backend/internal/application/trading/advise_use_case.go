package trading

import (
	"context"
	"sort"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domainNotifications "github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// AdviseUseCase builds stateless trading advice from broker snapshot + market.
type AdviseUseCase struct {
	ctx            *Context
	deploySessions *DeploySessionUseCase
	broker         *BrokerFacade
	notifications  domainNotifications.Repository
}

func NewAdviseUseCase(ctx *Context, deploySessions *DeploySessionUseCase, broker *BrokerFacade, notifications domainNotifications.Repository) *AdviseUseCase {
	return &AdviseUseCase{ctx: ctx, deploySessions: deploySessions, broker: broker, notifications: notifications}
}

func (u *AdviseUseCase) GetAdvice(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy *domainPortfolio.DurationPolicy) (application.TradingAdviceResult, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return application.TradingAdviceResult{}, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(kind, accountID)
	if err != nil {
		return application.TradingAdviceResult{}, err
	}
	ops, err := u.broker.GetAccountOperations(kind, accountID, OperationsFromDate(today))
	if err != nil {
		return application.TradingAdviceResult{}, err
	}
	orders, err := u.broker.GetActiveOrders(kind, accountID)
	if err != nil {
		return application.TradingAdviceResult{}, err
	}
	return u.BuildAdviceResult(ctx, p, universe, snapshot, ops, orders, keyRate, taxRate, today, durationPolicy)
}

func (u *AdviseUseCase) BuildAdviceResult(ctx context.Context, p domainPortfolio.Portfolio, universe []bonds.BondRecord, snapshot trading.InfraAccountSnapshot, operations []trading.InfraOperationRecord, activeOrders []trading.InfraOrderState, keyRate, taxRate float64, today time.Time, durationPolicy *domainPortfolio.DurationPolicy) (application.TradingAdviceResult, error) {
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	policy := durationPolicyOrDefault(p, durationPolicy)
	var activeSession *trading.DeploySession
	if u.deploySessions != nil {
		session, err := u.deploySessions.SyncActiveSession(ctx, p.ID, universe, &p, tinvest.ToBrokerActiveOrders(activeOrders))
		if err != nil {
			return application.TradingAdviceResult{}, err
		}
		activeSession = session
	}
	advice := trading.Advise(p, brokerSnapshot, tinvest.ToBrokerActiveOrders(activeOrders), tinvest.ToBrokerOperations(operations), universe, trading.AdviseParams{
		KeyRate: keyRate, TaxRate: taxRate, Today: &today, DurationPolicy: policy, ActiveSession: activeSession,
	})
	if u.notifications != nil {
		if recs, err := u.notifications.ListForPortfolio(ctx, p.ID, true); err == nil {
			advice.Suggestions = append(advice.Suggestions, turboEntrySuggestionsFromNotifications(p.ID, recs)...)
		}
	}
	var deploySession *trading.DeploySession
	if u.deploySessions != nil && advice.DeploySession != nil {
		persisted, err := u.deploySessions.SaveSession(ctx, *advice.DeploySession)
		if err != nil {
			return application.TradingAdviceResult{}, err
		}
		deploySession = &persisted
	}
	return application.TradingAdviceResult{
		Holdings:              advice.Holdings,
		Cashflow:              cashflowEventsToMaps(advice.Cashflow),
		Performance:           advice.Performance,
		Suggestions:           advice.Suggestions,
		ActiveOrders:          advice.ActiveOrders,
		MoneyRub:              advice.MoneyRub,
		AvailableMoneyRub:     advice.AvailableMoneyRub,
		BlockedMoneyRub:       advice.BlockedMoneyRub,
		Warnings:              advice.Warnings,
		AsOf:                  advice.AsOf,
		WeightedDurationYears: advice.WeightedDurationYears,
		DeploySession:         deploySession,
	}, nil
}

func turboEntrySuggestionsFromNotifications(portfolioID string, recs []domainNotifications.NotificationRecord) []trading.Suggestion {
	var out []trading.Suggestion
	for _, n := range recs {
		if n.Kind != "turbo_entry" {
			continue
		}
		isin, _ := n.Payload["isin"].(string)
		name, _ := n.Payload["name"].(string)
		reason, _ := n.Payload["reason"].(string)
		if isin == "" || name == "" {
			continue
		}
		lots := 1
		if v, ok := n.Payload["lots"].(float64); ok && v >= 1 {
			lots = int(v)
		}
		var suggested *float64
		if v, ok := n.Payload["suggested_price_pct"].(float64); ok {
			suggested = &v
		}
		var market *float64
		if v, ok := n.Payload["market_price_pct"].(float64); ok {
			market = &v
		}
		var figi *string
		if v, ok := n.Payload["figi"].(string); ok && v != "" {
			figi = &v
		}
		out = append(out, trading.Suggestion{
			ID:               trading.StableID(portfolioID, "turbo_entry_buy", isin),
			Kind:             trading.SuggestionKindBuy,
			ISIN:             isin,
			Name:             name,
			Lots:             lots,
			FIGI:             figi,
			SuggestedPricePct: suggested,
			MarketPricePct:    market,
			Reason:           reason,
			Urgency:          trading.SuggestionUrgency(n.Urgency),
		})
	}
	return out
}

func (u *AdviseUseCase) GetPerformance(ctx context.Context, portfolioID string) (map[string]any, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	today := time.Now()
	snapshot, err := u.broker.GetAccountSnapshot(kind, accountID)
	if err != nil {
		return nil, err
	}
	ops, err := u.broker.GetAccountOperations(kind, accountID, OperationsFromDate(today))
	if err != nil {
		return nil, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	holdings := trading.BuildHoldings(brokerSnapshot, nil)
	positions := trading.HoldingsToPositions(holdings, map[string]bonds.BondRecord{}, today, nil)
	perfPortfolio := p
	perfPortfolio.Positions = positions
	perf := trading.SummarizeActualPerformance(perfPortfolio, brokerSnapshot, tinvest.ToBrokerOperations(ops), today)
	return map[string]any{
		"xirr_pct":             perf.XIRRPct,
		"coupons_received_rub": perf.CouponsReceivedRub,
		"tax_paid_rub":         perf.TaxPaidRub,
		"money_rub":            float64(snapshot.MoneyRub),
	}, nil
}

func (u *AdviseUseCase) GetAccountOperations(ctx context.Context, portfolioID string) ([]trading.BrokerOperation, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return nil, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	today := time.Now()
	ops, err := u.broker.GetAccountOperations(kind, accountID, OperationsFromDate(today))
	if err != nil {
		return nil, err
	}
	brokerOps := tinvest.ToBrokerOperations(ops)
	sort.Slice(brokerOps, func(i, j int) bool {
		return brokerOps[i].Date.After(brokerOps[j].Date)
	})
	return brokerOps, nil
}

func cashflowEventsToMaps(events []domainPortfolio.CashflowEvent) []map[string]any {
	result := make([]map[string]any, 0, len(events))
	for _, e := range events {
		result = append(result, map[string]any{
			"date": e.Date.Format("2006-01-02"), "kind": e.Kind, "amount_rub": e.AmountRub,
			"description": e.Description, "related_isin": e.RelatedISIN, "is_projected": e.IsProjected,
			"lots": e.Lots, "bonds_count": e.BondsCount,
		})
	}
	return result
}

func mapTradingErr(err error) error {
	if err == nil {
		return nil
	}
	if err.Error() == "portfolio not found" || err.Error() == "portfolio is not in trading mode" {
		return application.ErrPortfolioNotFound
	}
	return err
}
