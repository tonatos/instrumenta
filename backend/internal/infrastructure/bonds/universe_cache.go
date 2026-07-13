package bonds

import (
	"crypto/sha256"
	"encoding/hex"
	"sync"
	"time"

	domainBonds "github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
)

const defaultTTL = 120 * time.Second

// CacheKey identifies an enriched bond universe cache entry.
type CacheKey struct {
	KeyRate          float64
	TaxRate          float64
	TokenFingerprint string
}

type cacheEntry struct {
	bonds    []domainBonds.BondRecord
	source   string
	cachedAt time.Time
}

var (
	cacheMu sync.RWMutex
	cache   = map[CacheKey]cacheEntry{}
	ttl     = defaultTTL
)

// ConfigureTTL sets shared cache TTL.
func ConfigureTTL(d time.Duration) {
	ttl = d
}

// TokenFingerprint returns a short hash of the trading token.
func TokenFingerprint(token string) string {
	if token == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:8])
}

// Get returns cached bonds if fresh.
func Get(key CacheKey) ([]domainBonds.BondRecord, string, bool) {
	cacheMu.RLock()
	entry, ok := cache[key]
	cacheMu.RUnlock()
	if !ok || time.Since(entry.cachedAt) >= ttl {
		return nil, "", false
	}
	return cloneBonds(entry.bonds), entry.source, true
}

// Put stores bonds in cache.
func Put(key CacheKey, bs []domainBonds.BondRecord, source string) {
	cacheMu.Lock()
	cache[key] = cacheEntry{bonds: cloneBonds(bs), source: source, cachedAt: time.Now()}
	cacheMu.Unlock()
}

// InvalidateAll clears the RAM cache.
func InvalidateAll() {
	cacheMu.Lock()
	cache = map[CacheKey]cacheEntry{}
	cacheMu.Unlock()
}

// CloneBondRecord returns a copy safe for duration scoring.
func CloneBondRecord(b domainBonds.BondRecord) domainBonds.BondRecord {
	cp := b
	if b.ProfileScores != nil {
		cp.ProfileScores = make(map[string]float64, len(b.ProfileScores))
		for k, v := range b.ProfileScores {
			cp.ProfileScores[k] = v
		}
	}
	return cp
}

func cloneBonds(bs []domainBonds.BondRecord) []domainBonds.BondRecord {
	out := make([]domainBonds.BondRecord, len(bs))
	for i, b := range bs {
		out[i] = CloneBondRecord(b)
	}
	return out
}
