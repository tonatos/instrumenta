package portfolio

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	domain "github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
)

type unset int

const unsetValue unset = 0

// Service provides CRUD and planning operations for portfolios.
type Service struct {
	repo domain.Repository
}

func NewService(repo domain.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) ListPortfolios(ctx context.Context) ([]domain.Portfolio, error) {
	return s.repo.ListAll(ctx)
}

func (s *Service) GetPortfolio(ctx context.Context, portfolioID string) (*domain.Portfolio, error) {
	return s.repo.GetByID(ctx, portfolioID)
}

func (s *Service) CreatePortfolio(ctx context.Context, name string, initialAmountRub float64, horizonDate time.Time, riskProfile domain.RiskProfile, apiTradeOnly bool, turboEntryEnabled bool, maxWeightedDurationYears, targetDurationYears *float64) (domain.Portfolio, error) {
	now := time.Now().UTC().Format(time.RFC3339)
	p := domain.Portfolio{
		ID: newPortfolioID(), Name: name, CreatedAt: now, UpdatedAt: now,
		InitialAmountRub: initialAmountRub, HorizonDate: horizonDate, RiskProfile: riskProfile,
		APITradeOnly: apiTradeOnly, TurboEntryEnabled: turboEntryEnabled, MaxWeightedDurationYears: maxWeightedDurationYears,
		TargetDurationYears: targetDurationYears, CashBalanceRub: initialAmountRub,
		Mode: domain.PortfolioModeSimulation, RiskBaselines: map[string]domain.RiskSnapshot{},
	}
	return s.repo.Save(ctx, p)
}

func (s *Service) UpdatePortfolio(ctx context.Context, p domain.Portfolio) (domain.Portfolio, error) {
	return s.repo.Save(ctx, p)
}

func (s *Service) DeletePortfolio(ctx context.Context, portfolioID string) (bool, error) {
	return s.repo.Delete(ctx, portfolioID)
}

func (s *Service) AutoComposePortfolio(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy *domain.DurationPolicy) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	policy := durationPolicyOrDefault(*p, durationPolicy)
	positions, remainingCash, _ := domain.AutoCompose(
		p.InitialAmountRub, universe, p.RiskProfile, p.HorizonDate, today,
		keyRate, taxRate, p.APITradeOnly, policy,
		&domain.DefaultDiversificationPolicy, nil,
	)
	p.Positions = positions
	p.CashBalanceRub = remainingCash
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) BuildPortfolioPlan(ctx context.Context, portfolioID string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, accountSnapshotMoneyRub *float64, assumeBestPutOutcome bool, durationPolicy *domain.DurationPolicy) (domain.PortfolioPlan, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.PortfolioPlan{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	if p.IsTrading() && accountSnapshotMoneyRub == nil {
		v := p.CashBalanceRub
		accountSnapshotMoneyRub = &v
		assumeBestPutOutcome = false
	}
	policy := durationPolicyOrDefault(*p, durationPolicy)
	plan := domain.BuildPlan(*p, universe, today, keyRate, taxRate, accountSnapshotMoneyRub, assumeBestPutOutcome, policy)
	if _, err := s.repo.Save(ctx, *p); err != nil {
		return domain.PortfolioPlan{}, err
	}
	return plan, nil
}

func (s *Service) UpdatePortfolioFields(ctx context.Context, portfolioID string, name *string, initialAmountRub *float64, horizonDate *time.Time, riskProfile *domain.RiskProfile, apiTradeOnly *bool, turboEntryEnabled *bool, maxWeightedDurationYears, targetDurationYears any) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	if name != nil {
		p.Name = *name
	}
	if initialAmountRub != nil {
		p.InitialAmountRub = *initialAmountRub
	}
	if horizonDate != nil {
		p.HorizonDate = *horizonDate
	}
	if riskProfile != nil {
		p.RiskProfile = *riskProfile
	}
	if apiTradeOnly != nil {
		p.APITradeOnly = *apiTradeOnly
	}
	if turboEntryEnabled != nil {
		p.TurboEntryEnabled = *turboEntryEnabled
	}
	if maxWeightedDurationYears != unsetValue {
		if maxWeightedDurationYears == nil {
			p.MaxWeightedDurationYears = nil
		} else if v, ok := maxWeightedDurationYears.(*float64); ok {
			p.MaxWeightedDurationYears = v
		}
	}
	if targetDurationYears != unsetValue {
		if targetDurationYears == nil {
			p.TargetDurationYears = nil
		} else if v, ok := targetDurationYears.(*float64); ok {
			p.TargetDurationYears = v
		}
	}
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) SetPutOfferDecision(ctx context.Context, portfolioID, isin, decision string) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	found := false
	for i := range p.Positions {
		if p.Positions[i].ISIN == isin {
			p.Positions[i].PutOfferDecision = bonds.PutOfferDecision(decision)
			found = true
			break
		}
	}
	if !found {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrPositionNotFound, isin)
	}
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) AddPosition(ctx context.Context, portfolioID string, universe []bonds.BondRecord, isin string, lots int, today time.Time) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	var bond *bonds.BondRecord
	for i := range universe {
		if universe[i].ISIN == isin {
			bond = &universe[i]
			break
		}
	}
	if bond == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrBondNotFound, isin)
	}
	if p.APITradeOnly && (bond.APITradeAvailableFlag == nil || !*bond.APITradeAvailableFlag) {
		return domain.Portfolio{}, fmt.Errorf("bond %s is not API-tradable", isin)
	}
	position := domain.PositionFromBond(*bond, lots, today, domain.PositionSourceInitial)
	p.Positions = append(p.Positions, position)
	p.CashBalanceRub = max(0, p.CashBalanceRub-position.PurchaseAmountRub)
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) RemovePosition(ctx context.Context, portfolioID, isin string) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	before := len(p.Positions)
	var kept []domain.PortfolioPosition
	for _, pos := range p.Positions {
		if pos.ISIN != isin {
			kept = append(kept, pos)
		}
	}
	if len(kept) == before {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrPositionNotFound, isin)
	}
	p.Positions = kept
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) ClearPositions(ctx context.Context, portfolioID string) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	p.Positions = nil
	p.Slots = nil
	p.CashBalanceRub = p.InitialAmountRub
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) SetSlotOverride(ctx context.Context, portfolioID, sourcePositionISIN string, confirmedISIN *string, universe []bonds.BondRecord, keyRate, taxRate float64, today time.Time, durationPolicy *domain.DurationPolicy) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	policy := durationPolicyOrDefault(*p, durationPolicy)
	plan := domain.BuildPlan(*p, universe, today, keyRate, taxRate, nil, true, policy)
	var slotContext *domain.ReinvestmentSlot
	for i := range plan.ResolvedSlots {
		if plan.ResolvedSlots[i].SourcePositionISIN != nil && *plan.ResolvedSlots[i].SourcePositionISIN == sourcePositionISIN {
			slotContext = &plan.ResolvedSlots[i]
			break
		}
	}
	if confirmedISIN != nil {
		if slotContext == nil {
			return domain.Portfolio{}, SlotOverrideValidationError{Message: "Слот реинвестиции для этой позиции не найден в плане"}
		}
		if reason := domain.ValidateSlotReplacement(*p, universe, *slotContext, *confirmedISIN); reason != nil {
			return domain.Portfolio{}, SlotOverrideValidationError{Message: *reason}
		}
	}
	for i := range p.Slots {
		if p.Slots[i].SourcePositionISIN != nil && *p.Slots[i].SourcePositionISIN == sourcePositionISIN {
			p.Slots[i].ConfirmedISIN = confirmedISIN
			p.Touch()
			return s.repo.Save(ctx, *p)
		}
	}
	p.Slots = append(p.Slots, domain.ReinvestmentSlot{
		TriggerDate: today, TriggerReason: domain.TriggerMaturity,
		SourcePositionISIN: &sourcePositionISIN, ConfirmedISIN: confirmedISIN,
	})
	p.Touch()
	return s.repo.Save(ctx, *p)
}

func (s *Service) ResetAllSlotOverrides(ctx context.Context, portfolioID string) (domain.Portfolio, error) {
	p, err := s.repo.GetByID(ctx, portfolioID)
	if err != nil || p == nil {
		return domain.Portfolio{}, fmt.Errorf("%w: %s", ErrNotFound, portfolioID)
	}
	changed := false
	for i := range p.Slots {
		if p.Slots[i].ConfirmedISIN != nil {
			p.Slots[i].ConfirmedISIN = nil
			changed = true
		}
	}
	if changed {
		p.Touch()
		return s.repo.Save(ctx, *p)
	}
	return *p, nil
}

func durationPolicyOrDefault(p domain.Portfolio, override *domain.DurationPolicy) domain.DurationPolicy {
	if override != nil {
		return *override
	}
	return domain.DurationPolicyForPortfolio(p, domain.RateScenarioHold)
}

func newPortfolioID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

// Unset is a sentinel for optional patch fields in UpdatePortfolioFields.
var Unset any = unsetValue
