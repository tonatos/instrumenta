package trading

import "context"

// DeploySessionRepository persists ephemeral deploy sessions.
type DeploySessionRepository interface {
	GetActive(ctx context.Context, portfolioID string) (*DeploySession, error)
	GetByID(ctx context.Context, sessionID string) (*DeploySession, error)
	Save(ctx context.Context, session DeploySession) (DeploySession, error)
	HasActive(ctx context.Context, portfolioID string) (bool, error)
}
