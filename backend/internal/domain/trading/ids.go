package trading

import "github.com/tonatos/bond-monitor/backend/internal/domain/shared"

// StableID returns a deterministic id for auto-generated operations.
func StableID(portfolioID, kind, key string) string {
	return shared.StableID(portfolioID, kind, key)
}
