package trading

import (
	"context"
	"fmt"
	"time"

	domainPortfolio "github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	appportfolio "github.com/tonatos/instrumenta/backend/internal/application/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/tinvest"
)

// BrokerPlanAdapter implements portfolio.BrokerPlanPort via BrokerFacade.
type BrokerPlanAdapter struct {
	broker *BrokerFacade
}

func NewBrokerPlanAdapter(broker *BrokerFacade) *BrokerPlanAdapter {
	return &BrokerPlanAdapter{broker: broker}
}

func (a *BrokerPlanAdapter) GetTradingSnapshot(ctx context.Context, p domainPortfolio.Portfolio) (trading.BrokerSnapshot, []trading.BrokerOperation, error) {
	if p.AccountID == nil || p.AccountKind == nil {
		return trading.BrokerSnapshot{}, nil, fmt.Errorf("portfolio is not linked to a broker account")
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := a.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return trading.BrokerSnapshot{}, nil, err
	}
	today := time.Now()
	ops, err := a.broker.GetAccountOperations(ctx, kind, accountID, OperationsFromDate(today))
	if err != nil {
		return trading.BrokerSnapshot{}, nil, err
	}
	return tinvest.ToBrokerSnapshot(snapshot), tinvest.ToBrokerOperations(ops), nil
}

// NewPlanUseCase wires the unified plan builder with broker access.
func NewPlanUseCase(repo domainPortfolio.Repository, broker *BrokerFacade) *appportfolio.PlanUseCase {
	return appportfolio.NewPlanUseCase(repo, NewBrokerPlanAdapter(broker))
}
