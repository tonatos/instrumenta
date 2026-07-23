package trading

import "strings"

// Access-level strings from T-Invest Account.access_level (proto enum .String()).
const (
	AccessLevelFullAccess  = "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS"
	AccessLevelReadOnly    = "ACCOUNT_ACCESS_LEVEL_READ_ONLY"
	AccessLevelNoAccess    = "ACCOUNT_ACCESS_LEVEL_NO_ACCESS"
	AccessLevelUnspecified = "ACCOUNT_ACCESS_LEVEL_UNSPECIFIED"
)

// AccountAllowsTrade reports whether the token may place/cancel orders on this account.
// T‑Invest marks read-only tokens with READ_ONLY; FULL_ACCESS means trade.
// Production full-access tokens sometimes return UNSPECIFIED — treat as tradeable unless
// the API explicitly says READ_ONLY / NO_ACCESS (false negatives blocked trading UX).
func AccountAllowsTrade(acc AccountInfo) bool {
	level := strings.TrimSpace(acc.AccessLevel)
	return level != AccessLevelReadOnly && level != AccessLevelNoAccess
}

// TokenCanTrade is true when at least one listed account allows trade.
// An empty list is inconclusive (caller should not persist "read-only").
func TokenCanTrade(accounts []AccountInfo) bool {
	for _, acc := range accounts {
		if AccountAllowsTrade(acc) {
			return true
		}
	}
	return false
}

// FindAccount returns the account with the given id, or nil.
func FindAccount(accounts []AccountInfo, accountID string) *AccountInfo {
	for i := range accounts {
		if accounts[i].ID == accountID {
			return &accounts[i]
		}
	}
	return nil
}
