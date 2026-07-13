package bonds

import (
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/screening"
	infraBonds "github.com/tonatos/bond-monitor/backend/internal/infrastructure/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/moex"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/ratings"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// LoadResult is the result of bond loading pipeline.
type LoadResult struct {
	Bonds  []bonds.BondRecord
	Source string
}

// Service is the application service for bond data loading and enrichment.
type Service struct {
	keyRate      float64
	taxRate      float64
	token        string
	maxDays      int
	minVolumeRub float64
	moex         bonds.MOEXClient
	ratings      bonds.RatingsLoader
	enricher     bonds.Enricher
}

// NewService creates a BondService with default infrastructure adapters.
func NewService(keyRate, taxRate float64, tinkoffToken string, maxDays int, minVolumeRub float64) *Service {
	return &Service{
		keyRate: keyRate, taxRate: taxRate, token: tinkoffToken, maxDays: maxDays, minVolumeRub: minVolumeRub,
		moex: moex.NewClient(), ratings: ratings.NewLoader(),
		enricher: tinvest.NewReadClient(tinkoffToken),
	}
}

// NewServiceWithDeps creates a BondService with injected ports (for tests).
func NewServiceWithDeps(keyRate, taxRate float64, maxDays int, minVolumeRub float64, moexClient bonds.MOEXClient, ratingsLoader bonds.RatingsLoader, enricher bonds.Enricher) *Service {
	return &Service{
		keyRate: keyRate, taxRate: taxRate, maxDays: maxDays, minVolumeRub: minVolumeRub,
		moex: moexClient, ratings: ratingsLoader, enricher: enricher,
	}
}

func (s *Service) screenerCacheKey(filterBy string) infraBonds.CacheKey {
	return infraBonds.CacheKey{
		KeyRate: s.keyRate, TaxRate: s.taxRate,
		TokenFingerprint: infraBonds.TokenFingerprint(s.token),
		Kind: infraBonds.CacheKindScreener, FilterBy: filterBy,
		MaxDays: s.maxDays, MinVolumeRub: s.minVolumeRub,
	}
}

func (s *Service) universeCacheKey() infraBonds.CacheKey {
	return infraBonds.CacheKey{
		KeyRate: s.keyRate, TaxRate: s.taxRate,
		TokenFingerprint: infraBonds.TokenFingerprint(s.token),
		Kind: infraBonds.CacheKindUniverse,
	}
}

func (s *Service) enrichAndScore(bs []bonds.BondRecord) ([]bonds.BondRecord, string) {
	source := "MOEX ISS API"
	bs = s.enricher.EnrichBonds(bs)
	if s.token != "" {
		source += " + T-Invest API"
	}
	r, _ := s.ratings.LoadRatings()
	auto, _ := s.ratings.LoadAutoRatings()
	bs = s.ratings.ApplyRatings(bs, r, auto)
	bs = screening.ScoreBondsAllProfiles(bs, s.keyRate, s.taxRate)
	return bs, source
}

func (s *Service) LoadScreenerBonds(filterBy string, policy portfolio.DurationPolicy, riskProfile portfolio.RiskProfile) LoadResult {
	key := s.screenerCacheKey(filterBy)
	if cached, source, ok := infraBonds.Get(key); ok {
		bs := cloneList(cached)
		bs = screening.SortBondsByResolvedScore(bs, toScreeningProfile(riskProfile), toScreeningDurationPolicy(policy))
		return LoadResult{Bonds: bs, Source: source}
	}
	bs, err := s.moex.FetchAllBonds(s.maxDays, s.minVolumeRub, filterBy)
	if err != nil {
		return LoadResult{}
	}
	bs, source := s.enrichAndScore(bs)
	infraBonds.Put(key, bs, source)
	bs = cloneList(bs)
	bs = screening.SortBondsByResolvedScore(bs, toScreeningProfile(riskProfile), toScreeningDurationPolicy(policy))
	return LoadResult{Bonds: bs, Source: source}
}

func (s *Service) LoadUniverse() LoadResult {
	key := s.universeCacheKey()
	if cached, source, ok := infraBonds.Get(key); ok {
		return LoadResult{Bonds: cloneList(cached), Source: source}
	}
	bs, err := s.moex.FetchAllBondsUnfiltered()
	if err != nil {
		return LoadResult{}
	}
	bs, source := s.enrichAndScore(bs)
	infraBonds.Put(key, bs, source)
	return LoadResult{Bonds: cloneList(bs), Source: source}
}

func (s *Service) LoadByISINs(isins []string, filterBy string, policy portfolio.DurationPolicy, riskProfile portfolio.RiskProfile) []bonds.BondRecord {
	if len(isins) == 0 {
		return nil
	}
	var found []bonds.BondRecord
	var missing map[string]struct{}
	screener := s.LoadScreenerBonds(filterBy, policy, riskProfile)
	byISIN := make(map[string]bonds.BondRecord, len(screener.Bonds))
	for _, b := range screener.Bonds {
		byISIN[b.ISIN] = b
	}
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
		scored := s.scoreAgainstCachedUniverse(fetched)
		found = append(found, scored...)
	}
	return found
}

func (s *Service) LoadBySecid(secid, filterBy string, policy portfolio.DurationPolicy, riskProfile portfolio.RiskProfile) *bonds.BondRecord {
	for _, b := range s.LoadScreenerBonds(filterBy, policy, riskProfile).Bonds {
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
	scored := s.scoreAgainstCachedUniverse([]bonds.BondRecord{*bond})
	if len(scored) == 0 {
		return nil
	}
	cp := scored[0]
	s.enricher.EnrichBondDetail(&cp)
	return &cp
}

func (s *Service) scoreAgainstCachedUniverse(bs []bonds.BondRecord) []bonds.BondRecord {
	universe := s.LoadUniverse()
	merged := append([]bonds.BondRecord{}, universe.Bonds...)
	seen := make(map[string]struct{})
	for _, b := range universe.Bonds {
		seen[b.Secid] = struct{}{}
	}
	for _, b := range bs {
		if _, ok := seen[b.Secid]; !ok {
			merged = append(merged, b)
		}
	}
	scored := screening.ScoreBondsAllProfiles(merged, s.keyRate, s.taxRate)
	bySecid := make(map[string]bonds.BondRecord, len(scored))
	for _, b := range scored {
		bySecid[b.Secid] = b
	}
	var result []bonds.BondRecord
	for _, b := range bs {
		if scored, ok := bySecid[b.Secid]; ok {
			result = append(result, scored)
		}
	}
	return result
}

func (s *Service) GetCouponSchedule(figi string) []bonds.CouponPayment {
	return s.enricher.GetCouponSchedule(figi)
}

func (s *Service) IsCacheFresh() bool {
	return s.moex.IsCacheFresh()
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
