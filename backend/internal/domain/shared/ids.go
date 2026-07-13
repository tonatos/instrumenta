package shared

import (
	"crypto/sha256"
	"encoding/hex"
)

// StableID returns a deterministic id for auto-generated operations.
func StableID(portfolioID, kind, key string) string {
	sum := sha256.Sum256([]byte(portfolioID + "|" + kind + "|" + key))
	return hex.EncodeToString(sum[:])[:32]
}
