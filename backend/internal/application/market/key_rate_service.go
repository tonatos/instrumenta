package market

import (
	"context"
	"log/slog"
	"strconv"
	"sync"
	"time"
)

const (
	SettingKeyRate          = "cbr_key_rate"
	SettingKeyRateFetchedAt = "cbr_key_rate_fetched_at"
	DefaultKeyRateTTL       = 24 * time.Hour
	// DefaultKeyRateFallback is used only when CBR and SQLite cache are unavailable.
	DefaultKeyRateFallback = 14.5
)

// SettingsStore persists opaque key/value app settings.
type SettingsStore interface {
	GetSetting(ctx context.Context, key string) (string, error)
	SetSetting(ctx context.Context, key, value string) error
}

// KeyRateFetcher loads the latest key rate from an upstream source (e.g. CBR).
type KeyRateFetcher interface {
	FetchLatestKeyRate(ctx context.Context, now time.Time) (rate float64, asOf time.Time, err error)
}

// KeyRateService caches the CBR key rate and refreshes at most once per TTL.
type KeyRateService struct {
	store    SettingsStore
	fetch    KeyRateFetcher
	fallback float64
	ttl      time.Duration
	logger   *slog.Logger
	now      func() time.Time
	onChange func(prev, next float64)

	mu        sync.RWMutex
	cached    float64
	fetchedAt time.Time
	hasCache  bool
}

func NewKeyRateService(store SettingsStore, fetch KeyRateFetcher, fallback float64, logger *slog.Logger) *KeyRateService {
	if fallback <= 0 {
		fallback = DefaultKeyRateFallback
	}
	return &KeyRateService{
		store:    store,
		fetch:    fetch,
		fallback: fallback,
		ttl:      DefaultKeyRateTTL,
		logger:   logger,
		now:      time.Now,
	}
}

// OnChange registers a callback when the effective key rate changes (e.g. invalidate bond cache).
func (s *KeyRateService) OnChange(fn func(prev, next float64)) {
	s.onChange = fn
}

// SetNowForTest overrides the clock (tests only).
func (s *KeyRateService) SetNowForTest(now func() time.Time) {
	if now != nil {
		s.now = now
	}
}

// Current returns the cached key rate (percent points), refreshing from CBR when stale.
func (s *KeyRateService) Current(ctx context.Context) float64 {
	s.mu.RLock()
	if s.hasCache && s.now().Sub(s.fetchedAt) < s.ttl {
		rate := s.cached
		s.mu.RUnlock()
		return rate
	}
	s.mu.RUnlock()

	s.mu.Lock()
	defer s.mu.Unlock()
	if s.hasCache && s.now().Sub(s.fetchedAt) < s.ttl {
		return s.cached
	}

	prev := s.effectiveLocked()
	if rate, ok := s.loadPersistedLocked(ctx); ok && s.now().Sub(s.fetchedAt) < s.ttl {
		s.notifyChange(prev, rate)
		return rate
	}

	if s.fetch != nil {
		rate, _, err := s.fetch.FetchLatestKeyRate(ctx, s.now())
		if err == nil && rate > 0 {
			s.persistLocked(ctx, rate, s.now())
			s.notifyChange(prev, rate)
			return rate
		}
		if s.logger != nil && err != nil {
			s.logger.Warn("cbr key rate fetch failed; using cache/fallback", "error", err)
		}
	}

	if s.hasCache {
		return s.cached
	}
	if rate, ok := s.loadPersistedLocked(ctx); ok {
		s.notifyChange(prev, rate)
		return rate
	}
	s.cached = s.fallback
	s.fetchedAt = s.now()
	s.hasCache = true
	s.notifyChange(prev, s.fallback)
	return s.fallback
}

// RefreshForce fetches from upstream ignoring TTL (still updates cache on success).
func (s *KeyRateService) RefreshForce(ctx context.Context) (float64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	prev := s.effectiveLocked()
	if s.fetch == nil {
		return s.effectiveLocked(), nil
	}
	rate, _, err := s.fetch.FetchLatestKeyRate(ctx, s.now())
	if err != nil {
		return s.effectiveLocked(), err
	}
	s.persistLocked(ctx, rate, s.now())
	s.notifyChange(prev, rate)
	return rate, nil
}

func (s *KeyRateService) effectiveLocked() float64 {
	if s.hasCache {
		return s.cached
	}
	return s.fallback
}

func (s *KeyRateService) loadPersistedLocked(ctx context.Context) (float64, bool) {
	if s.store == nil {
		return 0, false
	}
	raw, err := s.store.GetSetting(ctx, SettingKeyRate)
	if err != nil || raw == "" {
		return 0, false
	}
	rate, err := strconv.ParseFloat(raw, 64)
	if err != nil || rate <= 0 {
		return 0, false
	}
	s.cached = rate
	s.hasCache = true
	if atRaw, err := s.store.GetSetting(ctx, SettingKeyRateFetchedAt); err == nil && atRaw != "" {
		if at, err := time.Parse(time.RFC3339, atRaw); err == nil {
			s.fetchedAt = at
		}
	}
	if s.fetchedAt.IsZero() {
		s.fetchedAt = s.now()
	}
	return rate, true
}

func (s *KeyRateService) persistLocked(ctx context.Context, rate float64, at time.Time) {
	s.cached = rate
	s.fetchedAt = at
	s.hasCache = true
	if s.store == nil {
		return
	}
	_ = s.store.SetSetting(ctx, SettingKeyRate, strconv.FormatFloat(rate, 'f', -1, 64))
	_ = s.store.SetSetting(ctx, SettingKeyRateFetchedAt, at.UTC().Format(time.RFC3339))
}

func (s *KeyRateService) notifyChange(prev, next float64) {
	if s.onChange == nil || prev == next {
		return
	}
	s.onChange(prev, next)
}
