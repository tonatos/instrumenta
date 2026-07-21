package trading

import (
	"context"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domainPortfolio "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// DeploySessionConflictError indicates an active deploy session already exists.
type DeploySessionConflictError struct{ Message string }

func (e DeploySessionConflictError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return "active deploy session already exists"
}

// DeploySessionNotFoundError indicates a missing deploy session.
type DeploySessionNotFoundError struct{ Message string }

func (e DeploySessionNotFoundError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return "deploy session not found"
}

// DeploySessionEmptyError indicates no buy/reinvest recommendations to freeze.
type DeploySessionEmptyError struct{ Message string }

func (e DeploySessionEmptyError) Error() string {
	if e.Message != "" {
		return e.Message
	}
	return "no buy/reinvest recommendations to freeze"
}

// DeploySessionUseCase manages deploy session lifecycle.
type DeploySessionUseCase struct {
	ctx    *Context
	repo   trading.DeploySessionRepository
	broker *BrokerFacade
	policy trading.DeploySessionPolicy
}

func NewDeploySessionUseCase(ctx *Context, repo trading.DeploySessionRepository, broker *BrokerFacade, policy trading.DeploySessionPolicy) *DeploySessionUseCase {
	return &DeploySessionUseCase{ctx: ctx, repo: repo, broker: broker, policy: policy}
}

func (u *DeploySessionUseCase) GetActive(ctx context.Context, portfolioID string) (*trading.DeploySession, error) {
	return u.repo.GetActive(ctx, portfolioID)
}

func (u *DeploySessionUseCase) SaveSession(ctx context.Context, session trading.DeploySession) (trading.DeploySession, error) {
	return u.repo.Save(ctx, session)
}

func (u *DeploySessionUseCase) CreateSession(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (trading.DeploySession, error) {
	active, err := u.repo.GetActive(ctx, portfolioID)
	if err != nil {
		return trading.DeploySession{}, err
	}
	if active != nil {
		completed := trading.CompleteSessionIfNoPending(*active)
		if completed.Status == trading.DeploySessionCompleted {
			if _, err := u.repo.Save(ctx, completed); err != nil {
				return trading.DeploySession{}, err
			}
		} else if trading.SessionHasPendingItems(*active) {
			return trading.DeploySession{}, DeploySessionConflictError{
				Message: "Уже есть активный план закупки — завершите или отмените его",
			}
		}
	}
	return u.buildAndSave(ctx, portfolioID, universe, keyRate, taxRate, today, nil)
}

func (u *DeploySessionUseCase) RefreshSession(ctx context.Context, portfolioID, sessionID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time) (trading.DeploySession, error) {
	existing, err := u.repo.GetByID(ctx, sessionID)
	if err != nil {
		return trading.DeploySession{}, err
	}
	if existing == nil || existing.PortfolioID != portfolioID {
		return trading.DeploySession{}, DeploySessionNotFoundError{Message: "Сессия не найдена"}
	}
	if existing.Status != trading.DeploySessionActive {
		return trading.DeploySession{}, DeploySessionNotFoundError{Message: "Сессия не активна"}
	}
	refreshed, err := u.buildAndSave(ctx, portfolioID, universe, keyRate, taxRate, today, &existing.ID)
	if err != nil {
		return trading.DeploySession{}, err
	}
	refreshed.CreatedAt = existing.CreatedAt
	refreshed.Warnings = nil
	return u.repo.Save(ctx, refreshed)
}

func (u *DeploySessionUseCase) buildAndSave(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, sessionID *string) (trading.DeploySession, error) {
	p, err := u.ctx.GetTradingPortfolio(ctx, portfolioID)
	if err != nil {
		return trading.DeploySession{}, err
	}
	kind := *p.AccountKind
	accountID := *p.AccountID
	snapshot, err := u.broker.GetAccountSnapshot(ctx, kind, accountID)
	if err != nil {
		return trading.DeploySession{}, err
	}
	brokerSnapshot := tinvest.ToBrokerSnapshot(snapshot)
	holdings := trading.BuildHoldings(brokerSnapshot, universe)
	positions := trading.EffectiveTradingPositions(p, brokerSnapshot, universe, today)
	durationPolicy := domainPortfolio.DurationPolicyForPortfolio(p, domainPortfolio.RateScenarioHold)
	session := trading.BuildDeploySessionPlan(
		p, holdings, positions, universe, float64(brokerSnapshot.AvailableMoneyRub()), today,
		keyRate, taxRate, domainPortfolio.DefaultBondSelectionPolicy, domainPortfolio.DefaultPlanningPolicy, durationPolicy, u.policy, nil, sessionID,
	)
	if len(session.Items) == 0 {
		return trading.DeploySession{}, DeploySessionEmptyError{Message: "Нет рекомендаций для фиксации плана"}
	}
	return u.repo.Save(ctx, session)
}

func (u *DeploySessionUseCase) SyncActiveSession(ctx context.Context, portfolioID string, universe []bonds.BondRecord, p *domainPortfolio.Portfolio, activeOrders []trading.BrokerActiveOrder) (*trading.DeploySession, error) {
	session, err := u.repo.GetActive(ctx, portfolioID)
	if err != nil || session == nil {
		return nil, err
	}
	updated := trading.SyncSessionWithOrders(*session, activeOrders)
	now := time.Now()
	updated = trading.ApplySessionStaleness(updated, universe, *p, u.policy, &now)
	updated, err = u.repo.Save(ctx, updated)
	if err != nil {
		return nil, err
	}
	return &updated, nil
}

func (u *DeploySessionUseCase) CancelSession(ctx context.Context, portfolioID, sessionID string) (trading.DeploySession, error) {
	session, err := u.repo.GetByID(ctx, sessionID)
	if err != nil {
		return trading.DeploySession{}, err
	}
	if session == nil || session.PortfolioID != portfolioID {
		return trading.DeploySession{}, DeploySessionNotFoundError{Message: "Сессия не найдена"}
	}
	now := time.Now().UTC()
	session.Status = trading.DeploySessionCancelled
	session.CompletedAt = &now
	return u.repo.Save(ctx, *session)
}

func (u *DeploySessionUseCase) SkipItem(ctx context.Context, portfolioID, sessionID, itemID string) (trading.DeploySession, error) {
	session, err := u.repo.GetByID(ctx, sessionID)
	if err != nil || session == nil || session.PortfolioID != portfolioID {
		return trading.DeploySession{}, DeploySessionNotFoundError{Message: "Сессия не найдена"}
	}
	if !trading.IsSessionActive(*session, nil) {
		return trading.DeploySession{}, DeploySessionNotFoundError{Message: "Сессия не активна"}
	}
	if trading.FindSessionItem(*session, itemID) == nil {
		return trading.DeploySession{}, DeploySessionNotFoundError{Message: "Позиция не найдена в плане"}
	}
	updated := trading.MarkItemSkipped(*session, itemID)
	return u.repo.Save(ctx, updated)
}

func (u *DeploySessionUseCase) OnOrderPlaced(ctx context.Context, portfolioID, suggestionID, orderID string) (*trading.DeploySession, error) {
	if suggestionID == "" {
		return nil, nil
	}
	session, err := u.repo.GetActive(ctx, portfolioID)
	if err != nil || session == nil {
		return nil, err
	}
	if trading.FindSessionItem(*session, suggestionID) == nil {
		return nil, nil
	}
	updated := trading.MarkItemPlaced(*session, suggestionID, orderID)
	saved, err := u.repo.Save(ctx, updated)
	if err != nil {
		return nil, err
	}
	return &saved, nil
}
