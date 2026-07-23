package adapters

import (
	"context"
	"errors"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/application"
	appportfolio "github.com/tonatos/instrumenta/backend/internal/application/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
)

// PortfolioService adapts portfolio.Service to application.PortfolioService.
type PortfolioService struct {
	inner *appportfolio.Service
}

func NewPortfolioService(inner *appportfolio.Service) *PortfolioService {
	return &PortfolioService{inner: inner}
}

func (s *PortfolioService) ListPortfolios(ctx context.Context) ([]portfolio.Portfolio, error) {
	return s.inner.ListPortfolios(ctx)
}

func (s *PortfolioService) CreatePortfolio(ctx context.Context, params application.CreatePortfolioParams) (portfolio.Portfolio, error) {
	p, err := s.inner.CreatePortfolio(
		ctx, params.Name, params.InitialAmountRub, params.HorizonDate, params.RiskProfile, params.APITradeOnly,
		params.TurboEntryEnabled,
		params.MaxWeightedDurationYears, params.TargetDurationYears,
	)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) GetPortfolio(ctx context.Context, id string) (*portfolio.Portfolio, error) {
	p, err := s.inner.GetPortfolio(ctx, id)
	if err != nil {
		return nil, mapPortfolioErr(err)
	}
	return p, nil
}

func (s *PortfolioService) DeletePortfolio(ctx context.Context, id string) (bool, error) {
	ok, err := s.inner.DeletePortfolio(ctx, id)
	return ok, mapPortfolioErr(err)
}

func (s *PortfolioService) UpdatePortfolio(ctx context.Context, id string, params application.UpdatePortfolioParams) (portfolio.Portfolio, error) {
	var maxWeighted, targetDuration any = appportfolio.Unset, appportfolio.Unset
	if params.SetMaxWeightedDuration {
		maxWeighted = params.MaxWeightedDurationYears
	}
	if params.SetTargetDuration {
		targetDuration = params.TargetDurationYears
	}
	p, err := s.inner.UpdatePortfolioFields(
		ctx, id, params.Name, params.InitialAmountRub, params.HorizonDate, params.RiskProfile, params.APITradeOnly,
		params.TurboEntryEnabled,
		maxWeighted, targetDuration,
	)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) ClearPositions(ctx context.Context, id string) (portfolio.Portfolio, error) {
	p, err := s.inner.ClearPositions(ctx, id)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) AddPosition(ctx context.Context, id string, universe []bonds.BondRecord, isin string, lots int, today time.Time) (portfolio.Portfolio, error) {
	p, err := s.inner.AddPosition(ctx, id, universe, isin, lots, today)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) RemovePosition(ctx context.Context, id, isin string) error {
	_, err := s.inner.RemovePosition(ctx, id, isin)
	return mapPortfolioErr(err)
}

func (s *PortfolioService) SetPutOfferDecision(ctx context.Context, id, isin, decision string) (portfolio.Portfolio, error) {
	p, err := s.inner.SetPutOfferDecision(ctx, id, isin, decision)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) SetSlotOverride(ctx context.Context, id string, sourceISIN string, confirmedISIN *string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.Portfolio, error) {
	p, err := s.inner.SetSlotOverride(ctx, id, sourceISIN, confirmedISIN, universe, keyRate, taxRate, today, &durationPolicy)
	if err != nil {
		var slotErr appportfolio.SlotOverrideValidationError
		if errors.As(err, &slotErr) {
			return portfolio.Portfolio{}, application.SlotOverrideError{Code: "invalid", Message: slotErr.Message}
		}
		return portfolio.Portfolio{}, mapPortfolioErr(err)
	}
	return p, nil
}

func (s *PortfolioService) ResetAllSlotOverrides(ctx context.Context, id string) (portfolio.Portfolio, error) {
	p, err := s.inner.ResetAllSlotOverrides(ctx, id)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) AutoComposePortfolio(ctx context.Context, id string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.Portfolio, error) {
	p, err := s.inner.AutoComposePortfolio(ctx, id, universe, keyRate, taxRate, today, &durationPolicy)
	return p, mapPortfolioErr(err)
}

func (s *PortfolioService) BuildPortfolioPlan(ctx context.Context, id string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy portfolio.DurationPolicy) (portfolio.PortfolioPlan, error) {
	plan, err := s.inner.BuildPortfolioPlan(ctx, id, universe, keyRate, taxRate, today, nil, true, &durationPolicy)
	if err != nil {
		return portfolio.PortfolioPlan{}, mapPortfolioErr(err)
	}
	return plan, nil
}

func mapPortfolioErr(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, appportfolio.ErrNotFound) {
		return application.ErrPortfolioNotFound
	}
	if errors.Is(err, appportfolio.ErrPositionNotFound) {
		return application.ErrPositionNotFound
	}
	if errors.Is(err, appportfolio.ErrBondNotFound) {
		return application.ErrBondNotFound
	}
	return err
}

var _ application.PortfolioService = (*PortfolioService)(nil)
