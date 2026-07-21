package portfolio

import (
	"context"
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/interfaces/auth"
)

// BrokerPlanPort loads live broker data required for trading plan builds.
type BrokerPlanPort interface {
	GetTradingSnapshot(ctx context.Context, p domain.Portfolio) (trading.BrokerSnapshot, []trading.BrokerOperation, error)
}

// PlanUseCase is the single orchestration entry for portfolio plan builds.
type PlanUseCase struct {
	repo   domain.Repository
	broker BrokerPlanPort
}

func NewPlanUseCase(repo domain.Repository, broker BrokerPlanPort) *PlanUseCase {
	return &PlanUseCase{repo: repo, broker: broker}
}

func (u *PlanUseCase) Build(
	ctx context.Context,
	portfolioID string,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	assumeBestPutOutcome bool,
	durationPolicy *domain.DurationPolicy,
) (domain.PortfolioPlan, error) {
	owner, ok := auth.OwnerTelegramID(ctx)
	var p *domain.Portfolio
	var err error
	if ok {
		p, err = u.repo.GetByIDForOwner(ctx, portfolioID, owner)
	} else {
		p, err = u.repo.GetByID(ctx, portfolioID)
	}
	if err != nil || p == nil {
		return domain.PortfolioPlan{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	policy := durationPolicyOrDefault(*p, durationPolicy)
	if p.IsTrading() {
		if u.broker == nil {
			return domain.PortfolioPlan{}, fmt.Errorf("trading plan requires broker snapshot")
		}
		snapshot, ops, err := u.broker.GetTradingSnapshot(ctx, *p)
		if err != nil {
			return domain.PortfolioPlan{}, err
		}
		return u.buildTradingPlan(ctx, *p, snapshot, ops, universe, today, keyRate, taxRate, policy)
	}
	planCtx := domain.NewSimulationPlanContext(*p, assumeBestPutOutcome)
	plan := domain.BuildPlan(*p, universe, today, keyRate, taxRate, planCtx, policy)
	if _, err := u.repo.Save(ctx, *p); err != nil {
		return domain.PortfolioPlan{}, err
	}
	return plan, nil
}

func (u *PlanUseCase) BuildForTrading(
	p domain.Portfolio,
	snapshot trading.BrokerSnapshot,
	ops []trading.BrokerOperation,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	durationPolicy domain.DurationPolicy,
) domain.PortfolioPlan {
	return u.buildTradingPlanSnapshot(p, snapshot, ops, universe, today, keyRate, taxRate, durationPolicy)
}

func (u *PlanUseCase) buildTradingPlan(
	ctx context.Context,
	p domain.Portfolio,
	snapshot trading.BrokerSnapshot,
	ops []trading.BrokerOperation,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	durationPolicy domain.DurationPolicy,
) (domain.PortfolioPlan, error) {
	plan := u.buildTradingPlanSnapshot(p, snapshot, ops, universe, today, keyRate, taxRate, durationPolicy)
	if _, err := u.repo.Save(ctx, p); err != nil {
		return domain.PortfolioPlan{}, err
	}
	return plan, nil
}

func (u *PlanUseCase) buildTradingPlanSnapshot(
	p domain.Portfolio,
	snapshot trading.BrokerSnapshot,
	ops []trading.BrokerOperation,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	durationPolicy domain.DurationPolicy,
) domain.PortfolioPlan {
	positions := trading.EffectiveTradingPositions(p, snapshot, universe, today)
	historical := trading.OperationsToCashflowEvents(ops, today)
	brokerCash := float64(snapshot.MoneyRub)
	historical, delta, largeNote := trading.ReconcileCashToBroker(historical, today, brokerCash)
	invested := domain.InvestedCapitalFromPositions(positions, snapshot.MoneyRub)
	planCtx := domain.PlanContext{
		Mode:               domain.PlanModeTrading,
		Positions:          positions,
		HistoricalEvents:   historical,
		BrokerCashRub:      brokerCash,
		InvestedCapitalRub: invested,
		AssumeBestPutOutcome: false,
	}
	plan := domain.BuildPlan(p, universe, today, keyRate, taxRate, planCtx, durationPolicy)
	if largeNote {
		plan.Notes = append(plan.Notes, fmt.Sprintf(
			"Сверка с брокером: расхождение %.0f ₽ (операции за lookback могут не покрывать всю историю счёта).",
			delta,
		))
	}
	return plan
}

// PlanForSlotValidation builds the same plan used for slot override validation.
func (u *PlanUseCase) PlanForSlotValidation(
	ctx context.Context,
	p domain.Portfolio,
	universe []bonds.BondRecord,
	today time.Time,
	keyRate, taxRate float64,
	durationPolicy domain.DurationPolicy,
) (domain.PortfolioPlan, error) {
	if p.IsTrading() {
		if u.broker == nil {
			return domain.PortfolioPlan{}, fmt.Errorf("trading plan requires broker snapshot")
		}
		snapshot, ops, err := u.broker.GetTradingSnapshot(ctx, p)
		if err != nil {
			return domain.PortfolioPlan{}, err
		}
		return u.buildTradingPlanSnapshot(p, snapshot, ops, universe, today, keyRate, taxRate, durationPolicy), nil
	}
	planCtx := domain.NewSimulationPlanContext(p, true)
	return domain.BuildPlan(p, universe, today, keyRate, taxRate, planCtx, durationPolicy), nil
}
