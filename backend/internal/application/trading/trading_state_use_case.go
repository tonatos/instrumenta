package trading

import (
	"context"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	appportfolio "github.com/tonatos/bond-monitor/backend/internal/application/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

const operationsLookbackDays = 365

// TradingStateUseCase returns combined trading plan + advice.
type TradingStateUseCase struct {
	ctx    *Context
	advise *AdviseUseCase
	broker *BrokerFacade
	plans  *appportfolio.PlanUseCase
}

func NewTradingStateUseCase(ctx *Context, advise *AdviseUseCase, broker *BrokerFacade, plans *appportfolio.PlanUseCase) *TradingStateUseCase {
	return &TradingStateUseCase{ctx: ctx, advise: advise, broker: broker, plans: plans}
}

func (u *TradingStateUseCase) GetTradingState(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy *domainPortfolio.DurationPolicy) (application.TradingStateResult, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return application.TradingStateResult{}, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return application.TradingStateResult{}, err
	}
	ops, err := u.broker.GetAccountOperations(ctx, kind, accountID, OperationsFromDate(today))
	if err != nil {
		return application.TradingStateResult{}, err
	}
	orders, err := u.broker.GetActiveOrders(ctx, kind, accountID)
	if err != nil {
		return application.TradingStateResult{}, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	brokerOps := tinvest.ToBrokerOperations(ops)
	policy := durationPolicyOrDefault(p, durationPolicy)
	plan := u.plans.BuildForTrading(p, brokerSnapshot, brokerOps, universe, today, keyRate, taxRate, policy)
	advice, err := u.advise.BuildAdviceResult(ctx, p, universe, snapshot, ops, orders, keyRate, taxRate, today, durationPolicy, plan.ResolvedSlots)
	if err != nil {
		return application.TradingStateResult{}, err
	}
	return application.TradingStateResult{Plan: plan, Advice: advice}, nil
}

// OperationsFromDate returns the lower bound for broker operations history.
func OperationsFromDate(today time.Time) time.Time {
	return today.AddDate(0, 0, -operationsLookbackDays)
}

func durationPolicyOrDefault(p domainPortfolio.Portfolio, override *domainPortfolio.DurationPolicy) domainPortfolio.DurationPolicy {
	if override != nil {
		return *override
	}
	return domainPortfolio.DurationPolicyForPortfolio(p, domainPortfolio.RateScenarioHold)
}
