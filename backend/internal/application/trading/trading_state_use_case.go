package trading

import (
	"context"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

const operationsLookbackDays = 365

// TradingStateUseCase returns combined trading plan + advice.
type TradingStateUseCase struct {
	ctx    *Context
	advise *AdviseUseCase
	broker *BrokerFacade
}

func NewTradingStateUseCase(ctx *Context, advise *AdviseUseCase, broker *BrokerFacade) *TradingStateUseCase {
	return &TradingStateUseCase{ctx: ctx, advise: advise, broker: broker}
}

func (u *TradingStateUseCase) GetTradingState(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy *domainPortfolio.DurationPolicy) (application.TradingStateResult, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return application.TradingStateResult{}, mapTradingErr(err)
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(kind, accountID)
	if err != nil {
		return application.TradingStateResult{}, err
	}
	ops, err := u.broker.GetAccountOperations(kind, accountID, OperationsFromDate(today))
	if err != nil {
		return application.TradingStateResult{}, err
	}
	orders, err := u.broker.GetActiveOrders(kind, accountID)
	if err != nil {
		return application.TradingStateResult{}, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	plan := BuildTradingPlan(p, brokerSnapshot, universe, keyRate, taxRate, today, durationPolicy)
	advice, err := u.advise.BuildAdviceResult(ctx, p, universe, snapshot, ops, orders, keyRate, taxRate, today, durationPolicy)
	if err != nil {
		return application.TradingStateResult{}, err
	}
	return application.TradingStateResult{Plan: plan, Advice: advice}, nil
}

// OperationsFromDate returns the lower bound for broker operations history.
func OperationsFromDate(today time.Time) time.Time {
	return today.AddDate(0, 0, -operationsLookbackDays)
}

// BuildTradingPlan builds a portfolio plan from live broker snapshot.
func BuildTradingPlan(p domainPortfolio.Portfolio, snapshot trading.BrokerSnapshot, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy *domainPortfolio.DurationPolicy) domainPortfolio.PortfolioPlan {
	positions := trading.EffectiveTradingPositions(p, snapshot, universe, today)
	ephemeral := p
	ephemeral.Positions = positions
	money := float64(snapshot.MoneyRub)
	policy := durationPolicyOrDefault(p, durationPolicy)
	return domainPortfolio.BuildPlan(ephemeral, universe, today, keyRate, taxRate, &money, false, policy)
}

func durationPolicyOrDefault(p domainPortfolio.Portfolio, override *domainPortfolio.DurationPolicy) domainPortfolio.DurationPolicy {
	if override != nil {
		return *override
	}
	return domainPortfolio.DurationPolicyForPortfolio(p, domainPortfolio.RateScenarioHold)
}
