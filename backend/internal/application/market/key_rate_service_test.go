package market_test

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/application/market"
)

type memStore struct {
	mu   sync.Mutex
	data map[string]string
}

func newMemStore() *memStore {
	return &memStore{data: map[string]string{}}
}

func (m *memStore) GetSetting(_ context.Context, key string) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.data[key], nil
}

func (m *memStore) SetSetting(_ context.Context, key, value string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.data[key] = value
	return nil
}

type stubFetcher struct {
	rate float64
	err  error
	n    int
}

func (f *stubFetcher) FetchLatestKeyRate(context.Context, time.Time) (float64, time.Time, error) {
	f.n++
	if f.err != nil {
		return 0, time.Time{}, f.err
	}
	return f.rate, time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC), nil
}

func TestKeyRateService_FetchesAndCaches(t *testing.T) {
	store := newMemStore()
	fetch := &stubFetcher{rate: 14.25}
	now := time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC)
	svc := market.NewKeyRateService(store, fetch, 16, nil)
	svc.SetNowForTest(func() time.Time { return now })

	if got := svc.Current(context.Background()); got != 14.25 {
		t.Fatalf("got %v", got)
	}
	if fetch.n != 1 {
		t.Fatalf("fetch count %d", fetch.n)
	}
	// Within TTL — no second fetch.
	now = now.Add(time.Hour)
	if got := svc.Current(context.Background()); got != 14.25 || fetch.n != 1 {
		t.Fatalf("got %v fetches=%d", got, fetch.n)
	}
	// After TTL — refresh.
	now = now.Add(24 * time.Hour)
	fetch.rate = 15
	if got := svc.Current(context.Background()); got != 15 || fetch.n != 2 {
		t.Fatalf("got %v fetches=%d", got, fetch.n)
	}
}

func TestKeyRateService_FallbackOnFetchError(t *testing.T) {
	store := newMemStore()
	fetch := &stubFetcher{err: errors.New("network")}
	svc := market.NewKeyRateService(store, fetch, 16.5, nil)
	svc.SetNowForTest(func() time.Time { return time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC) })

	if got := svc.Current(context.Background()); got != 16.5 {
		t.Fatalf("got %v want fallback", got)
	}
}

func TestKeyRateService_UsesPersistedWhenFresh(t *testing.T) {
	store := newMemStore()
	_ = store.SetSetting(context.Background(), market.SettingKeyRate, "14.25")
	_ = store.SetSetting(context.Background(), market.SettingKeyRateFetchedAt, time.Date(2026, 7, 23, 10, 0, 0, 0, time.UTC).Format(time.RFC3339))
	fetch := &stubFetcher{rate: 99}
	svc := market.NewKeyRateService(store, fetch, 16, nil)
	svc.SetNowForTest(func() time.Time { return time.Date(2026, 7, 23, 12, 0, 0, 0, time.UTC) })

	if got := svc.Current(context.Background()); got != 14.25 {
		t.Fatalf("got %v", got)
	}
	if fetch.n != 0 {
		t.Fatalf("should not fetch when persisted is fresh, n=%d", fetch.n)
	}
}

func TestKeyRateService_OnChange(t *testing.T) {
	store := newMemStore()
	fetch := &stubFetcher{rate: 14}
	svc := market.NewKeyRateService(store, fetch, 16, nil)
	svc.SetNowForTest(func() time.Time { return time.Date(2026, 7, 23, 0, 0, 0, 0, time.UTC) })
	var changes [][2]float64
	svc.OnChange(func(prev, next float64) { changes = append(changes, [2]float64{prev, next}) })

	_ = svc.Current(context.Background())
	if len(changes) != 1 || changes[0][0] != 16 || changes[0][1] != 14 {
		t.Fatalf("changes=%v", changes)
	}
}
