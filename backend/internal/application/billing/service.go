package billing

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/billing"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/yookassa"
)

var (
	ErrSubscriptionRequired = errors.New("subscription_required")
	ErrPaymentUnavailable   = errors.New("payment_unavailable")
	ErrInvalidPeriod        = errors.New("invalid_period")
	ErrNoSubscription       = errors.New("no_subscription")
	ErrInvalidChange        = errors.New("invalid_period_change")
)

// Store is the persistence port for billing.
type Store interface {
	ListCurrentPlanVersions(ctx context.Context) ([]billing.PlanVersion, error)
	GetPlanVersionByID(ctx context.Context, id string) (*billing.PlanVersion, error)
	GetCurrentPlanByPeriod(ctx context.Context, period billing.Period) (*billing.PlanVersion, error)
	GetSubscriptionByOwner(ctx context.Context, ownerTelegramID int64) (*billing.Subscription, error)
	SaveSubscription(ctx context.Context, sub billing.Subscription) (billing.Subscription, error)
	ListSubscriptionsDueForRenew(ctx context.Context, now time.Time) ([]billing.Subscription, error)
	CreatePayment(ctx context.Context, p billing.Payment) (billing.Payment, error)
	UpdatePayment(ctx context.Context, p billing.Payment) error
	GetPaymentByID(ctx context.Context, id string) (*billing.Payment, error)
	GetPaymentByYooKassaID(ctx context.Context, yooID string) (*billing.Payment, error)
	GetPaymentByIdempotencyKey(ctx context.Context, key string) (*billing.Payment, error)
	AddLedgerEntry(ctx context.Context, e billing.LedgerEntry) (billing.LedgerEntry, error)
	ListLedger(ctx context.Context, ownerTelegramID int64, limit int) ([]billing.LedgerEntry, error)
}

// Service orchestrates billing use cases.
type Service struct {
	Store            Store
	Gateway          yookassa.PaymentGateway
	ComplimentaryIDs map[int64]struct{}
	ReturnURL        string
	Policy           billing.Policy
}

func NewService(store Store, gateway yookassa.PaymentGateway, complimentary []int64, returnURL string) *Service {
	ids := make(map[int64]struct{}, len(complimentary))
	for _, id := range complimentary {
		ids[id] = struct{}{}
	}
	if gateway == nil {
		gateway = yookassa.DisabledGateway{}
	}
	return &Service{
		Store:            store,
		Gateway:          gateway,
		ComplimentaryIDs: ids,
		ReturnURL:        returnURL,
		Policy:           billing.DefaultPolicy(),
	}
}

func (s *Service) IsComplimentary(ownerTelegramID int64) bool {
	_, ok := s.ComplimentaryIDs[ownerTelegramID]
	return ok
}

func (s *Service) PaymentEnabled() bool {
	return s.Gateway != nil && s.Gateway.Enabled()
}

func (s *Service) accessInput(ctx context.Context, ownerTelegramID int64, now time.Time) (billing.AccessInput, error) {
	if s.IsComplimentary(ownerTelegramID) {
		return billing.AccessInput{Complimentary: true, Now: now, Policy: s.Policy}, nil
	}
	sub, err := s.Store.GetSubscriptionByOwner(ctx, ownerTelegramID)
	if err != nil {
		return billing.AccessInput{}, err
	}
	return billing.AccessInput{Subscription: sub, Now: now, Policy: s.Policy}, nil
}

// RequireFeature returns ErrSubscriptionRequired when access is denied.
func (s *Service) RequireFeature(ctx context.Context, ownerTelegramID int64, feature billing.Feature) error {
	in, err := s.accessInput(ctx, ownerTelegramID, time.Now().UTC())
	if err != nil {
		return err
	}
	if !billing.HasAccess(in, feature) {
		return ErrSubscriptionRequired
	}
	return nil
}

// HasFeature is a non-erroring check.
func (s *Service) HasFeature(ctx context.Context, ownerTelegramID int64, feature billing.Feature) (bool, error) {
	in, err := s.accessInput(ctx, ownerTelegramID, time.Now().UTC())
	if err != nil {
		return false, err
	}
	return billing.HasAccess(in, feature), nil
}

// CatalogDTO is API catalog payload.
type CatalogDTO struct {
	Plans          []billing.CatalogItem `json:"plans"`
	PaymentEnabled bool                  `json:"payment_enabled"`
}

func (s *Service) GetCatalog(ctx context.Context) (CatalogDTO, error) {
	plans, err := s.Store.ListCurrentPlanVersions(ctx)
	if err != nil {
		return CatalogDTO{}, err
	}
	var monthKopecks int64
	for _, p := range plans {
		if p.Period == billing.PeriodMonth {
			monthKopecks = p.AmountKopecks
		}
	}
	items := make([]billing.CatalogItem, 0, len(plans))
	for _, p := range plans {
		item := billing.CatalogItem{
			Period:         p.Period,
			AmountKopecks:  p.AmountKopecks,
			MonthlyKopecks: billing.EffectiveMonthlyKopecks(p.Period, p.AmountKopecks),
			Features:       p.Features,
			PlanVersionID:  p.ID,
		}
		if p.Period == billing.PeriodYear && monthKopecks > 0 {
			item.SavingsKopecks = billing.YearlySavingsKopecks(monthKopecks, p.AmountKopecks)
			item.SavingsPercent = billing.YearlySavingsPercent(monthKopecks, p.AmountKopecks)
		}
		items = append(items, item)
	}
	return CatalogDTO{
		Plans:          items,
		PaymentEnabled: s.PaymentEnabled(),
	}, nil
}

// StatusDTO is subscription status for the client (no payment_method_id).
type StatusDTO struct {
	Complimentary    bool     `json:"complimentary"`
	PaymentEnabled   bool     `json:"payment_enabled"`
	Entitlements     []string `json:"entitlements"`
	HasActiveAccess  bool     `json:"has_active_access"`
	Subscription     *SubDTO  `json:"subscription,omitempty"`
}

type SubDTO struct {
	Status            string    `json:"status"`
	Period            string    `json:"period"`
	AmountKopecks     int64     `json:"amount_kopecks"`
	CurrentPeriodEnd  time.Time `json:"current_period_end"`
	CancelAtPeriodEnd bool      `json:"cancel_at_period_end"`
	Features          []string  `json:"features"`
}

func (s *Service) GetStatus(ctx context.Context, ownerTelegramID int64) (StatusDTO, error) {
	now := time.Now().UTC()
	in, err := s.accessInput(ctx, ownerTelegramID, now)
	if err != nil {
		return StatusDTO{}, err
	}
	ents := billing.EntitledFeatures(in)
	entStr := make([]string, 0, len(ents))
	for _, f := range ents {
		entStr = append(entStr, string(f))
	}
	dto := StatusDTO{
		Complimentary:   s.IsComplimentary(ownerTelegramID),
		PaymentEnabled:  s.PaymentEnabled(),
		Entitlements:    entStr,
		HasActiveAccess: len(ents) > 0,
	}
	if in.Subscription != nil {
		feats := make([]string, 0, len(in.Subscription.Features))
		for _, f := range in.Subscription.Features {
			feats = append(feats, string(f))
		}
		dto.Subscription = &SubDTO{
			Status:            string(in.Subscription.Status),
			Period:            string(in.Subscription.Period),
			AmountKopecks:     in.Subscription.AmountKopecks,
			CurrentPeriodEnd:  in.Subscription.CurrentPeriodEnd,
			CancelAtPeriodEnd: in.Subscription.CancelAtPeriodEnd,
			Features:          feats,
		}
	}
	return dto, nil
}

type CheckoutResult struct {
	PaymentID       string `json:"payment_id"`
	ConfirmationURL string `json:"confirmation_url"`
	Status          string `json:"status"`
}

func (s *Service) CreateCheckout(ctx context.Context, ownerTelegramID int64, period billing.Period, purpose string) (CheckoutResult, error) {
	if purpose == "" {
		purpose = "checkout"
	}
	if !s.PaymentEnabled() {
		return CheckoutResult{}, ErrPaymentUnavailable
	}
	if period != billing.PeriodMonth && period != billing.PeriodYear {
		return CheckoutResult{}, ErrInvalidPeriod
	}
	plan, err := s.Store.GetCurrentPlanByPeriod(ctx, period)
	if err != nil {
		return CheckoutResult{}, err
	}
	if plan == nil {
		return CheckoutResult{}, fmt.Errorf("plan not found for period %s", period)
	}
	if purpose == "change_period" {
		if period != billing.PeriodYear {
			return CheckoutResult{}, ErrInvalidChange
		}
		sub, err := s.Store.GetSubscriptionByOwner(ctx, ownerTelegramID)
		if err != nil {
			return CheckoutResult{}, err
		}
		if sub == nil || !billing.IsEntitled(false, sub, billing.FeaturePortfolioAttach, time.Now().UTC()) {
			return CheckoutResult{}, ErrNoSubscription
		}
		if sub.Period == billing.PeriodYear {
			return CheckoutResult{}, ErrInvalidChange
		}
	}

	idem := fmt.Sprintf("%s-%d-%s-%d", purpose, ownerTelegramID, period, time.Now().UTC().UnixNano())
	pay, err := s.Store.CreatePayment(ctx, billing.Payment{
		OwnerTelegramID: ownerTelegramID,
		PlanVersionID:   plan.ID,
		Period:          period,
		AmountKopecks:   plan.AmountKopecks,
		Status:          billing.PaymentPending,
		IdempotencyKey:  idem,
		Purpose:         purpose,
	})
	if err != nil {
		return CheckoutResult{}, err
	}

	desc := "Instrumenta Pro — месяц"
	if period == billing.PeriodYear {
		desc = "Instrumenta Pro — год"
	}
	created, err := s.Gateway.CreatePayment(ctx, yookassa.CreatePaymentRequest{
		AmountKopecks:       plan.AmountKopecks,
		Description:         desc,
		ReturnURL:           s.ReturnURL,
		IdempotencyKey:      idem,
		SavePaymentMethod:   true,
		Metadata: map[string]string{
			"owner_telegram_id": strconv.FormatInt(ownerTelegramID, 10),
			"payment_id":        pay.ID,
			"plan_period":       string(period),
			"purpose":           purpose,
		},
	})
	if err != nil {
		if errors.Is(err, yookassa.ErrPaymentUnavailable) {
			return CheckoutResult{}, ErrPaymentUnavailable
		}
		return CheckoutResult{}, err
	}
	pay.YooKassaPaymentID = created.ID
	pay.ConfirmationURL = created.ConfirmationURL
	if created.Paid && created.Status == "succeeded" {
		pay.Status = billing.PaymentSucceeded
	}
	if err := s.Store.UpdatePayment(ctx, pay); err != nil {
		return CheckoutResult{}, err
	}
	if pay.Status == billing.PaymentSucceeded {
		if err := s.applyVerifiedPayment(ctx, pay, created.PaymentMethodID); err != nil {
			return CheckoutResult{}, err
		}
	}
	return CheckoutResult{
		PaymentID:       pay.ID,
		ConfirmationURL: pay.ConfirmationURL,
		Status:          string(pay.Status),
	}, nil
}

func (s *Service) ChangePeriodToYear(ctx context.Context, ownerTelegramID int64) (CheckoutResult, error) {
	return s.CreateCheckout(ctx, ownerTelegramID, billing.PeriodYear, "change_period")
}

func (s *Service) Cancel(ctx context.Context, ownerTelegramID int64) error {
	sub, err := s.Store.GetSubscriptionByOwner(ctx, ownerTelegramID)
	if err != nil {
		return err
	}
	if sub == nil {
		return ErrNoSubscription
	}
	now := time.Now().UTC()
	updated := billing.MarkCancelAtPeriodEnd(*sub, now)
	_, err = s.Store.SaveSubscription(ctx, updated)
	return err
}

// HandleYooKassaWebhook processes a notification. Never trusts body amount — re-fetches payment.
func (s *Service) HandleYooKassaWebhook(ctx context.Context, yooPaymentID string) error {
	if yooPaymentID == "" {
		return fmt.Errorf("empty payment id")
	}
	if !s.PaymentEnabled() {
		return ErrPaymentUnavailable
	}
	info, err := s.Gateway.GetPayment(ctx, yooPaymentID)
	if err != nil {
		return err
	}
	pay, err := s.Store.GetPaymentByYooKassaID(ctx, yooPaymentID)
	if err != nil {
		return err
	}
	if pay == nil {
		// Fallback: metadata payment_id
		if pid := info.Metadata["payment_id"]; pid != "" {
			pay, err = s.Store.GetPaymentByID(ctx, pid)
			if err != nil {
				return err
			}
		}
	}
	if pay == nil {
		return fmt.Errorf("unknown payment %s", yooPaymentID)
	}
	if pay.Status == billing.PaymentSucceeded {
		return nil // idempotent
	}
	if info.Status != "succeeded" || !info.Paid {
		if info.Status == "canceled" {
			pay.Status = billing.PaymentCanceled
			return s.Store.UpdatePayment(ctx, *pay)
		}
		return nil
	}
	if info.AmountKopecks != pay.AmountKopecks {
		return fmt.Errorf("amount mismatch: expected %d got %d", pay.AmountKopecks, info.AmountKopecks)
	}
	ownerMeta := info.Metadata["owner_telegram_id"]
	if ownerMeta != "" && ownerMeta != strconv.FormatInt(pay.OwnerTelegramID, 10) {
		return fmt.Errorf("owner mismatch")
	}
	pay.Status = billing.PaymentSucceeded
	pay.YooKassaPaymentID = info.ID
	if err := s.Store.UpdatePayment(ctx, *pay); err != nil {
		return err
	}
	return s.applyVerifiedPayment(ctx, *pay, info.PaymentMethodID)
}

func (s *Service) applyVerifiedPayment(ctx context.Context, pay billing.Payment, paymentMethodID string) error {
	plan, err := s.Store.GetPlanVersionByID(ctx, pay.PlanVersionID)
	if err != nil {
		return err
	}
	if plan == nil {
		return fmt.Errorf("plan %s missing", pay.PlanVersionID)
	}
	now := time.Now().UTC()
	existing, err := s.Store.GetSubscriptionByOwner(ctx, pay.OwnerTelegramID)
	if err != nil {
		return err
	}
	updated := billing.ApplySuccessfulPayment(existing, *plan, pay.OwnerTelegramID, pay.Purpose, now, paymentMethodID)
	if _, err := s.Store.SaveSubscription(ctx, updated); err != nil {
		return err
	}
	reason := "subscription_" + string(pay.Period)
	if pay.Purpose == "change_period" {
		reason = "change_period_year"
	} else if pay.Purpose == "renew" {
		reason = "renewal_" + string(pay.Period)
	}
	_, err = s.Store.AddLedgerEntry(ctx, billing.LedgerEntry{
		OwnerTelegramID: pay.OwnerTelegramID,
		Kind:            billing.LedgerDebit,
		AmountKopecks:   pay.AmountKopecks,
		Reason:          reason,
		PaymentID:       pay.ID,
		CreatedAt:       now,
	})
	return err
}

func (s *Service) ListLedger(ctx context.Context, ownerTelegramID int64, limit int) ([]billing.LedgerEntry, error) {
	return s.Store.ListLedger(ctx, ownerTelegramID, limit)
}

// RenewDue charges due subscriptions and expires canceled/past_due after grace.
func (s *Service) RenewDue(ctx context.Context, now time.Time) (renewed, failed, expired int, err error) {
	if now.IsZero() {
		now = time.Now().UTC()
	}
	subs, err := s.Store.ListSubscriptionsDueForRenew(ctx, now)
	if err != nil {
		return 0, 0, 0, err
	}
	for _, sub := range subs {
		if s.IsComplimentary(sub.OwnerTelegramID) {
			continue
		}
		if billing.ShouldExpireCanceled(sub, now) {
			updated := billing.MarkExpired(sub, now)
			if updated.Status == billing.StatusCanceled || sub.CancelAtPeriodEnd {
				updated.Status = billing.StatusExpired
			}
			if _, e := s.Store.SaveSubscription(ctx, updated); e != nil {
				return renewed, failed, expired, e
			}
			expired++
			continue
		}
		if billing.ShouldExpirePastDue(sub, now, s.Policy) {
			updated := billing.MarkExpired(sub, now)
			if _, e := s.Store.SaveSubscription(ctx, updated); e != nil {
				return renewed, failed, expired, e
			}
			expired++
			continue
		}
		if !billing.ShouldAttemptRenew(sub, now) {
			if sub.CancelAtPeriodEnd && (sub.CurrentPeriodEnd.Before(now) || sub.CurrentPeriodEnd.Equal(now)) {
				updated := billing.MarkExpired(sub, now)
				if _, e := s.Store.SaveSubscription(ctx, updated); e != nil {
					return renewed, failed, expired, e
				}
				expired++
			}
			continue
		}
		if !s.PaymentEnabled() {
			updated := billing.MarkPastDue(sub, now)
			if _, e := s.Store.SaveSubscription(ctx, updated); e != nil {
				return renewed, failed, expired, e
			}
			failed++
			continue
		}
		idem := fmt.Sprintf("renew-%s-%d", sub.ID, now.Unix())
		if existing, _ := s.Store.GetPaymentByIdempotencyKey(ctx, idem); existing != nil {
			if existing.Status == billing.PaymentSucceeded {
				renewed++
				continue
			}
		}
		pay, e := s.Store.CreatePayment(ctx, billing.Payment{
			OwnerTelegramID: sub.OwnerTelegramID,
			PlanVersionID:   sub.PlanVersionID,
			Period:          sub.Period,
			AmountKopecks:   sub.AmountKopecks, // grandfathered
			Status:          billing.PaymentPending,
			IdempotencyKey:  idem,
			Purpose:         "renew",
		})
		if e != nil {
			return renewed, failed, expired, e
		}
		created, e := s.Gateway.CreatePayment(ctx, yookassa.CreatePaymentRequest{
			AmountKopecks:   sub.AmountKopecks,
			Description:     "Instrumenta Pro — продление",
			IdempotencyKey:  idem,
			PaymentMethodID: sub.PaymentMethodID,
			Metadata: map[string]string{
				"owner_telegram_id": strconv.FormatInt(sub.OwnerTelegramID, 10),
				"payment_id":        pay.ID,
				"plan_period":       string(sub.Period),
				"purpose":           "renew",
			},
		})
		if e != nil {
			updated := billing.MarkPastDue(sub, now)
			_, _ = s.Store.SaveSubscription(ctx, updated)
			pay.Status = billing.PaymentFailed
			_ = s.Store.UpdatePayment(ctx, pay)
			failed++
			continue
		}
		pay.YooKassaPaymentID = created.ID
		if created.Paid || created.Status == "succeeded" {
			pay.Status = billing.PaymentSucceeded
			if e := s.Store.UpdatePayment(ctx, pay); e != nil {
				return renewed, failed, expired, e
			}
			if e := s.applyVerifiedPayment(ctx, pay, firstNonEmpty(created.PaymentMethodID, sub.PaymentMethodID)); e != nil {
				return renewed, failed, expired, e
			}
			renewed++
			continue
		}
		_ = s.Store.UpdatePayment(ctx, pay)
		// pending — leave; webhook will finish
	}
	return renewed, failed, expired, nil
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}
