package adapters

import (
	"context"

	"github.com/tonatos/bond-monitor/backend/internal/application"
	appbonds "github.com/tonatos/bond-monitor/backend/internal/application/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/tinvest"
)

// BondService adapts bonds.Service to application.BondService.
type BondService struct {
	inner *appbonds.Service
}

func NewBondService(inner *appbonds.Service) *BondService {
	return &BondService{inner: inner}
}

func (s *BondService) ListBonds(ctx context.Context, query bonds.BondListQuery, riskProfile portfolio.RiskProfile, rateScenario string) (application.BondListLoadResult, error) {
	_ = ctx
	policy := portfolio.ResolveDurationPolicy(portfolio.RateScenario(rateScenario), nil, nil)
	result := s.inner.ListBonds(query, policy, riskProfile)
	return application.BondListLoadResult{
		Bonds: result.Bonds, Total: result.Total,
		Page: result.Page, PageSize: result.PageSize, Source: result.Source,
	}, nil
}

func (s *BondService) LoadUniverse(ctx context.Context) (application.BondLoadResult, error) {
	_ = ctx
	result := s.inner.LoadUniverse()
	return application.BondLoadResult{Bonds: result.Bonds, Source: result.Source}, nil
}

func (s *BondService) LoadBySecid(ctx context.Context, secid string, riskProfile portfolio.RiskProfile, rateScenario string) (*bonds.BondRecord, error) {
	_ = ctx
	policy := portfolio.ResolveDurationPolicy(portfolio.RateScenario(rateScenario), nil, nil)
	return s.inner.LoadBySecid(secid, policy, riskProfile), nil
}

func (s *BondService) LoadByISINs(ctx context.Context, isins []string, riskProfile portfolio.RiskProfile, rateScenario string) ([]bonds.BondRecord, error) {
	_ = ctx
	policy := portfolio.ResolveDurationPolicy(portfolio.RateScenario(rateScenario), nil, nil)
	return s.inner.LoadByISINs(isins, policy, riskProfile), nil
}

func (s *BondService) GetCouponSchedule(ctx context.Context, figi string) ([]map[string]any, error) {
	_ = ctx
	schedule := s.inner.GetCouponSchedule(figi)
	out := make([]map[string]any, 0, len(schedule))
	for _, c := range schedule {
		item := map[string]any{}
		if c.PaymentDate != nil {
			item["payment_date"] = c.PaymentDate.Format("2006-01-02")
		}
		if c.AmountRub != nil {
			item["amount_rub"] = *c.AmountRub
		}
		item["coupon_type_raw"] = c.CouponTypeRaw
		out = append(out, item)
	}
	return out, nil
}

func (s *BondService) RefreshRatings(ctx context.Context) (int, error) {
	return s.inner.RefreshRatings(ctx)
}

func (s *BondService) InvalidateCaches(ctx context.Context) error {
	_ = ctx
	s.inner.InvalidateCaches()
	tinvest.InvalidateBondsCache()
	return nil
}

var _ application.BondService = (*BondService)(nil)
