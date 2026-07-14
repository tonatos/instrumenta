package moex

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

const (
	defaultFlagsStaleTTL = 24 * time.Hour
	defaultFetchWorkers  = 8
)

// DefaultFlags describes MOEX default status for one ISIN.
type DefaultFlags struct {
	HasDefault          bool
	HasTechnicalDefault bool
}

type defaultFlagsRepo interface {
	UpsertMOEXDefaultFlags(ctx context.Context, flags map[string]persistence.BondDefaultFlagRow) (int, error)
	ListDefaultFlags(ctx context.Context) (map[string]persistence.BondDefaultFlagRow, error)
	DefaultsRefreshedAt(ctx context.Context) (time.Time, error)
}

// DefaultFlagsService loads MOEX default flags into SQLite and applies them to bonds.
type DefaultFlagsService struct {
	httpClient *http.Client
	repo       defaultFlagsRepo

	mu        sync.Mutex
	refreshAt time.Time
}

func NewDefaultFlagsService(repo defaultFlagsRepo) *DefaultFlagsService {
	return &DefaultFlagsService{
		httpClient: &http.Client{Timeout: 30 * time.Second},
		repo:       repo,
	}
}

func (s *DefaultFlagsService) Apply(ctx context.Context, bs []bonds.BondRecord) []bonds.BondRecord {
	flags, err := s.repo.ListDefaultFlags(ctx)
	if err != nil || len(flags) == 0 {
		return bs
	}
	for i := range bs {
		if f, ok := flags[strings.ToUpper(bs[i].ISIN)]; ok {
			bs[i].HasDefault = f.HasDefault
			bs[i].HasTechnicalDefault = f.HasTechnicalDefault
		}
	}
	return bs
}

func (s *DefaultFlagsService) RefreshIfStale(ctx context.Context, bs []bonds.BondRecord) error {
	if !s.needsRefresh(ctx) {
		return nil
	}
	return s.RefreshFromMOEX(ctx, bs)
}

func (s *DefaultFlagsService) RefreshFromMOEX(ctx context.Context, bs []bonds.BondRecord) error {
	secids := uniqueSecids(bs)
	if len(secids) == 0 {
		return nil
	}
	flags, err := fetchDefaultFlagsFromMOEX(ctx, s.httpClient, secids)
	if err != nil {
		return err
	}
	rows := make(map[string]persistence.BondDefaultFlagRow, len(flags))
	for isin, flag := range flags {
		rows[isin] = persistence.BondDefaultFlagRow{
			ISIN:                isin,
			HasDefault:          flag.HasDefault,
			HasTechnicalDefault: flag.HasTechnicalDefault,
			Source:              persistence.DefaultSourceMOEX,
		}
	}
	if _, err := s.repo.UpsertMOEXDefaultFlags(ctx, rows); err != nil {
		return err
	}
	s.mu.Lock()
	s.refreshAt = time.Now().UTC()
	s.mu.Unlock()
	return nil
}

func (s *DefaultFlagsService) InvalidateCache() {
	s.mu.Lock()
	s.refreshAt = time.Time{}
	s.mu.Unlock()
}

func (s *DefaultFlagsService) needsRefresh(ctx context.Context) bool {
	s.mu.Lock()
	local := s.refreshAt
	s.mu.Unlock()
	if !local.IsZero() && time.Since(local) < defaultFlagsStaleTTL {
		return false
	}
	at, err := s.repo.DefaultsRefreshedAt(ctx)
	if err != nil || at.IsZero() {
		return true
	}
	s.mu.Lock()
	s.refreshAt = at
	s.mu.Unlock()
	return time.Since(at) >= defaultFlagsStaleTTL
}

func uniqueSecids(bs []bonds.BondRecord) []string {
	seen := make(map[string]struct{}, len(bs))
	var out []string
	for _, b := range bs {
		secid := strings.TrimSpace(b.Secid)
		if secid == "" {
			continue
		}
		if _, ok := seen[secid]; ok {
			continue
		}
		seen[secid] = struct{}{}
		out = append(out, secid)
	}
	return out
}

func fetchDefaultFlagsFromMOEX(ctx context.Context, client *http.Client, secids []string) (map[string]DefaultFlags, error) {
	type result struct {
		isin  string
		flags DefaultFlags
		err   error
	}
	jobs := make(chan string)
	results := make(chan result, len(secids))

	workers := defaultFetchWorkers
	if workers > len(secids) {
		workers = len(secids)
	}
	if workers < 1 {
		workers = 1
	}

	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for secid := range jobs {
				isin, flags, err := fetchOneDefaultFlags(ctx, client, secid)
				results <- result{isin: isin, flags: flags, err: err}
			}
		}()
	}
	go func() {
		for _, secid := range secids {
			jobs <- secid
		}
		close(jobs)
		wg.Wait()
		close(results)
	}()

	out := make(map[string]DefaultFlags, len(secids))
	var firstErr error
	for res := range results {
		if res.err != nil {
			if firstErr == nil {
				firstErr = res.err
			}
			continue
		}
		if res.isin != "" {
			out[res.isin] = res.flags
		}
	}
	if len(out) == 0 && firstErr != nil {
		return nil, firstErr
	}
	return out, firstErr
}

func fetchOneDefaultFlags(ctx context.Context, client *http.Client, secid string) (string, DefaultFlags, error) {
	url := fmt.Sprintf("%s/securities/%s.json?iss.meta=off", issBase, secid)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", DefaultFlags{}, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", DefaultFlags{}, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", DefaultFlags{}, err
	}
	return parseDefaultFlagsDescription(body)
}

func parseDefaultFlagsDescription(body []byte) (string, DefaultFlags, error) {
	var payload struct {
		Description struct {
			Data [][]any `json:"data"`
		} `json:"description"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return "", DefaultFlags{}, err
	}
	fields := map[string]string{}
	for _, row := range payload.Description.Data {
		if len(row) < 3 {
			continue
		}
		key, _ := row[0].(string)
		val := fmt.Sprint(row[2])
		fields[key] = val
	}
	isin := strings.ToUpper(strings.TrimSpace(fields["ISIN"]))
	if isin == "" {
		return "", DefaultFlags{}, fmt.Errorf("missing ISIN in MOEX description")
	}
	return isin, DefaultFlags{
		HasDefault:          parseMOEXBool(fields["HASDEFAULT"]),
		HasTechnicalDefault: parseMOEXBool(fields["HASTECHNICALDEFAULT"]),
	}, nil
}

func parseMOEXBool(v string) bool {
	switch strings.TrimSpace(strings.ToLower(v)) {
	case "1", "true", "yes":
		return true
	default:
		return false
	}
}

var _ bonds.DefaultFlagsApplier = (*DefaultFlagsService)(nil)
