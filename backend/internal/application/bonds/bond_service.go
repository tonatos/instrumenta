package bonds

import (
	"context"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/screening"
	infraBonds "github.com/tonatos/bond-monitor/backend/internal/infrastructure/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/moex"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// LoadResult is the result of bond loading pipeline.
type LoadResult struct {
	Bonds  []bonds.BondRecord
	Source string
}

// Service is the application service for bond data loading and enrichment.
type Service struct {
	keyRate  float64
	taxRate  float64
	token    string
	moex     bonds.MOEXClient
	ratings  bonds.RatingsLoader
	enricher bonds.Enricher
	defaults bonds.DefaultFlagsApplier
}

// NewService creates a BondService with default infrastructure adapters.
func NewService(keyRate, taxRate float64, tinkoffToken string) *Service {
	return &Service{
		keyRate: keyRate, taxRate: taxRate, token: tinkoffToken,
		moex:     moex.NewClient(),
		enricher: tinvest.NewReadClient(tinkoffToken),
	}
}

// NewServiceWithDeps creates a BondService with injected ports (for tests).
func NewServiceWithDeps(
	keyRate, taxRate float64,
	token string,
	moexClient bonds.MOEXClient,
	ratingsLoader bonds.RatingsLoader,
	enricher bonds.Enricher,
	defaults bonds.DefaultFlagsApplier,
) *Service {
	return &Service{
		keyRate: keyRate, taxRate: taxRate, token: token,
		moex: moexClient, ratings: ratingsLoader, enricher: enricher, defaults: defaults,
	}
}

func (s *Service) universeCacheKey() infraBonds.CacheKey {
	return infraBonds.CacheKey{
		KeyRate:          s.keyRate,
		TaxRate:          s.taxRate,
		TokenFingerprint: infraBonds.TokenFingerprint(s.token),
	}
}

func (s *Service) enrichAndScore(ctx context.Context, bs []bonds.BondRecord) ([]bonds.BondRecord, string) {
	source := "MOEX ISS API"
	bs = s.enricher.EnrichBonds(bs)
	if s.token != "" {
		source += " + T-Invest API"
	}
	if s.defaults != nil {
		_ = s.defaults.RefreshIfStale(ctx, bs)
		bs = s.defaults.Apply(ctx, bs)
	}
	if s.ratings != nil {
		bs = s.ratings.ApplyRatings(ctx, bs)
	}
	bs = screening.ScoreBondsAllProfiles(bs, s.keyRate, s.taxRate)
	return bs, source
}

func (s *Service) LoadUniverse() LoadResult {
	ctx := context.Background()
	if s.ratings != nil {
		s.ratings.MaybeRefreshStale(ctx)
	}
	key := s.universeCacheKey()
	if cached, source, ok := infraBonds.Get(key); ok {
		return LoadResult{Bonds: cloneList(cached), Source: source}
	}
	bs, err := s.moex.FetchAllBondsUnfiltered()
	if err != nil {
		return LoadResult{}
	}
	bs, source := s.enrichAndScore(ctx, bs)
	infraBonds.Put(key, bs, source)
	return LoadResult{Bonds: cloneList(bs), Source: source}
}

// RefreshRatings scrapes smart-lab and stores ISIN ratings in SQLite.
func (s *Service) RefreshRatings(ctx context.Context) (int, error) {
	if s.ratings == nil {
		return 0, nil
	}
	count, err := s.ratings.RefreshFromSmartLab(ctx)
	if err != nil {
		return count, err
	}
	InvalidateAllBondCaches()
	return count, nil
}

// ListBonds filters, sorts, and paginates the enriched universe.
func (s *Service) ListBonds(
	query bonds.BondListQuery,
	policy portfolio.DurationPolicy,
	riskProfile portfolio.RiskProfile,
) bonds.BondListResult {
	query = bonds.NormalizeBondListQuery(query)
	universe := s.LoadUniverse()
	filtered := bonds.FilterBondList(cloneList(universe.Bonds), query)
	screenPolicy := toScreeningDurationPolicy(policy)
	profile := toScreeningProfile(riskProfile)
	if query.SortBy == "score" {
		filtered = screening.SortBondsByResolvedScore(filtered, profile, screenPolicy)
		// SortBondsByResolvedScore already returns highest score first.
		if !query.SortDesc {
			filtered = reverseBondList(filtered)
		}
	} else {
		filtered = bonds.SortBondList(filtered, query)
	}
	page, total := bonds.PaginateBondList(filtered, query)
	return bonds.BondListResult{
		Bonds: page, Total: total,
		Page: query.Page, PageSize: query.PageSize,
		Source: universe.Source,
	}
}

func reverseBondList(list []bonds.BondRecord) []bonds.BondRecord {
	out := make([]bonds.BondRecord, len(list))
	for i, b := range list {
		out[len(list)-1-i] = b
	}
	return out
}

func (s *Service) LoadByISINs(isins []string, policy portfolio.DurationPolicy, riskProfile portfolio.RiskProfile) []bonds.BondRecord {
	if len(isins) == 0 {
		return nil
	}
	universe := s.LoadUniverse()
	byISIN := make(map[string]bonds.BondRecord, len(universe.Bonds))
	for _, b := range universe.Bonds {
		byISIN[b.ISIN] = b
	}
	var found []bonds.BondRecord
	var missing map[string]struct{}
	for _, isin := range isins {
		if b, ok := byISIN[isin]; ok {
			found = append(found, infraBonds.CloneBondRecord(b))
		} else {
			if missing == nil {
				missing = make(map[string]struct{})
			}
			missing[isin] = struct{}{}
		}
	}
	if len(missing) > 0 {
		fetched, _ := s.moex.FetchBondsByISINs(missing)
		scored := s.enrichFetchedBonds(fetched)
		found = append(found, scored...)
	}
	_ = policy
	_ = riskProfile
	return found
}

func (s *Service) LoadBySecid(secid string, policy portfolio.DurationPolicy, riskProfile portfolio.RiskProfile) *bonds.BondRecord {
	for _, b := range s.LoadUniverse().Bonds {
		if b.Secid == secid {
			cp := infraBonds.CloneBondRecord(b)
			s.enricher.EnrichBondDetail(&cp)
			return &cp
		}
	}
	bond, _ := s.moex.FetchBondBySecid(secid)
	if bond == nil {
		return nil
	}
	scored := s.enrichFetchedBonds([]bonds.BondRecord{*bond})
	if len(scored) == 0 {
		return nil
	}
	cp := scored[0]
	s.enricher.EnrichBondDetail(&cp)
	_ = policy
	_ = riskProfile
	return &cp
}

func (s *Service) enrichFetchedBonds(bs []bonds.BondRecord) []bonds.BondRecord {
	if len(bs) == 0 {
		return nil
	}
	enriched, _ := s.enrichAndScore(context.Background(), bs)
	return enriched
}

func (s *Service) scoreAgainstCachedUniverse(bs []bonds.BondRecord) []bonds.BondRecord {
	return s.enrichFetchedBonds(bs)
}

func (s *Service) GetCouponSchedule(figi string) []bonds.CouponPayment {
	return s.enricher.GetCouponSchedule(figi)
}

func (s *Service) IsCacheFresh() bool {
	return s.moex.IsCacheFresh()
}

func (s *Service) InvalidateCaches() {
	InvalidateAllBondCaches()
	s.moex.InvalidateCache()
	tinvest.InvalidateBondsCache()
	if s.defaults != nil {
		s.defaults.InvalidateCache()
	}
}

func cloneList(bs []bonds.BondRecord) []bonds.BondRecord {
	out := make([]bonds.BondRecord, len(bs))
	for i, b := range bs {
		out[i] = infraBonds.CloneBondRecord(b)
	}
	return out
}

func toScreeningProfile(p portfolio.RiskProfile) screening.RiskProfile {
	return screening.RiskProfile(p)
}

func toScreeningDurationPolicy(p portfolio.DurationPolicy) screening.DurationPolicy {
	return screening.DurationPolicy{
		RateScenario:             screening.RateScenario(p.RateScenario),
		DurationScoreWeight:      p.DurationScoreWeight,
		TargetDurationYears:      p.TargetDurationYears,
		MaxWeightedDurationYears: p.MaxWeightedDurationYears,
		FloaterRateDurationYears: p.FloaterRateDurationYears,
	}
}

// InvalidateAllBondCaches clears shared enriched-universe RAM cache.
func InvalidateAllBondCaches() { infraBonds.InvalidateAll() }
