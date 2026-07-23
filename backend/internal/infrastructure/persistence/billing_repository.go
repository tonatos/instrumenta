package persistence

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/billing"
)

// BillingRepository persists plans, subscriptions, payments, and ledger.
type BillingRepository struct {
	db *DB
}

func NewBillingRepository(db *DB) *BillingRepository {
	return &BillingRepository{db: db}
}

func billingNewID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

func marshalFeatures(features []billing.Feature) (string, error) {
	if features == nil {
		features = []billing.Feature{}
	}
	b, err := json.Marshal(features)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func unmarshalFeatures(raw string) ([]billing.Feature, error) {
	if raw == "" {
		return nil, nil
	}
	var features []billing.Feature
	if err := json.Unmarshal([]byte(raw), &features); err != nil {
		return nil, err
	}
	return features, nil
}

type planVersionRow struct {
	ID            string `db:"id"`
	CatalogGroup  string `db:"catalog_group"`
	Code          string `db:"code"`
	Period        string `db:"period"`
	AmountKopecks int64  `db:"amount_kopecks"`
	FeaturesJSON  string `db:"features_json"`
	EffectiveFrom string `db:"effective_from"`
	IsCurrent     int    `db:"is_current"`
}

func planFromRow(row planVersionRow) (billing.PlanVersion, error) {
	features, err := unmarshalFeatures(row.FeaturesJSON)
	if err != nil {
		return billing.PlanVersion{}, err
	}
	ef, err := time.Parse(time.RFC3339, row.EffectiveFrom)
	if err != nil {
		return billing.PlanVersion{}, err
	}
	return billing.PlanVersion{
		ID:            row.ID,
		CatalogGroup:  row.CatalogGroup,
		Code:          row.Code,
		Period:        billing.Period(row.Period),
		AmountKopecks: row.AmountKopecks,
		Features:      features,
		EffectiveFrom: ef,
		IsCurrent:     row.IsCurrent != 0,
	}, nil
}

// ListCurrentPlanVersions returns is_current=1 plans.
func (r *BillingRepository) ListCurrentPlanVersions(ctx context.Context) ([]billing.PlanVersion, error) {
	var rows []planVersionRow
	err := r.db.SelectContext(ctx, &rows, `
		SELECT id, catalog_group, code, period, amount_kopecks, features_json, effective_from, is_current
		FROM billing_plan_versions WHERE is_current = 1 ORDER BY period
	`)
	if err != nil {
		return nil, err
	}
	out := make([]billing.PlanVersion, 0, len(rows))
	for _, row := range rows {
		p, err := planFromRow(row)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, nil
}

// GetPlanVersionByID loads any plan version (including non-current for grandfathering).
func (r *BillingRepository) GetPlanVersionByID(ctx context.Context, id string) (*billing.PlanVersion, error) {
	var row planVersionRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, catalog_group, code, period, amount_kopecks, features_json, effective_from, is_current
		FROM billing_plan_versions WHERE id = $1
	`, id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := planFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// GetCurrentPlanByPeriod returns the current plan for month|year.
func (r *BillingRepository) GetCurrentPlanByPeriod(ctx context.Context, period billing.Period) (*billing.PlanVersion, error) {
	var row planVersionRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, catalog_group, code, period, amount_kopecks, features_json, effective_from, is_current
		FROM billing_plan_versions WHERE is_current = 1 AND period = $1 LIMIT 1
	`, string(period))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := planFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

type subscriptionRow struct {
	ID                 string         `db:"id"`
	OwnerTelegramID    int64          `db:"owner_telegram_id"`
	Status             string         `db:"status"`
	PlanVersionID      string         `db:"plan_version_id"`
	Period             string         `db:"period"`
	AmountKopecks      int64          `db:"amount_kopecks"`
	FeaturesJSON       string         `db:"features_json"`
	CurrentPeriodStart string         `db:"current_period_start"`
	CurrentPeriodEnd   string         `db:"current_period_end"`
	CancelAtPeriodEnd  int            `db:"cancel_at_period_end"`
	PaymentMethodID    string         `db:"payment_method_id"`
	PastDueSince       sql.NullString `db:"past_due_since"`
	CreatedAt          string         `db:"created_at"`
	UpdatedAt          string         `db:"updated_at"`
}

func subscriptionFromRow(row subscriptionRow) (billing.Subscription, error) {
	features, err := unmarshalFeatures(row.FeaturesJSON)
	if err != nil {
		return billing.Subscription{}, err
	}
	start, err := time.Parse(time.RFC3339, row.CurrentPeriodStart)
	if err != nil {
		return billing.Subscription{}, err
	}
	end, err := time.Parse(time.RFC3339, row.CurrentPeriodEnd)
	if err != nil {
		return billing.Subscription{}, err
	}
	created, err := time.Parse(time.RFC3339, row.CreatedAt)
	if err != nil {
		return billing.Subscription{}, err
	}
	updated, err := time.Parse(time.RFC3339, row.UpdatedAt)
	if err != nil {
		return billing.Subscription{}, err
	}
	var pastDue *time.Time
	if row.PastDueSince.Valid && row.PastDueSince.String != "" {
		t, err := time.Parse(time.RFC3339, row.PastDueSince.String)
		if err != nil {
			return billing.Subscription{}, err
		}
		pastDue = &t
	}
	return billing.Subscription{
		ID:                 row.ID,
		OwnerTelegramID:    row.OwnerTelegramID,
		Status:             billing.SubscriptionStatus(row.Status),
		PlanVersionID:      row.PlanVersionID,
		Period:             billing.Period(row.Period),
		AmountKopecks:      row.AmountKopecks,
		Features:           features,
		CurrentPeriodStart: start,
		CurrentPeriodEnd:   end,
		CancelAtPeriodEnd:  row.CancelAtPeriodEnd != 0,
		PaymentMethodID:    row.PaymentMethodID,
		PastDueSince:       pastDue,
		CreatedAt:          created,
		UpdatedAt:          updated,
	}, nil
}

// GetSubscriptionByOwner returns the owner's subscription or nil.
func (r *BillingRepository) GetSubscriptionByOwner(ctx context.Context, ownerTelegramID int64) (*billing.Subscription, error) {
	var row subscriptionRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, owner_telegram_id, status, plan_version_id, period, amount_kopecks, features_json,
			current_period_start, current_period_end, cancel_at_period_end, payment_method_id,
			past_due_since, created_at, updated_at
		FROM billing_subscriptions WHERE owner_telegram_id = $1
	`, ownerTelegramID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	s, err := subscriptionFromRow(row)
	if err != nil {
		return nil, err
	}
	return &s, nil
}

// SaveSubscription upserts by owner_telegram_id.
func (r *BillingRepository) SaveSubscription(ctx context.Context, sub billing.Subscription) (billing.Subscription, error) {
	if sub.ID == "" {
		sub.ID = billingNewID()
	}
	now := time.Now().UTC()
	if sub.CreatedAt.IsZero() {
		sub.CreatedAt = now
	}
	sub.UpdatedAt = now
	featuresJSON, err := marshalFeatures(sub.Features)
	if err != nil {
		return billing.Subscription{}, err
	}
	var pastDue any
	if sub.PastDueSince != nil {
		pastDue = sub.PastDueSince.UTC().Format(time.RFC3339)
	}
	cancel := 0
	if sub.CancelAtPeriodEnd {
		cancel = 1
	}
	_, err = r.db.ExecContext(ctx, `
		INSERT INTO billing_subscriptions (
			id, owner_telegram_id, status, plan_version_id, period, amount_kopecks, features_json,
			current_period_start, current_period_end, cancel_at_period_end, payment_method_id,
			past_due_since, created_at, updated_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
		ON CONFLICT(owner_telegram_id) DO UPDATE SET
			status = excluded.status,
			plan_version_id = excluded.plan_version_id,
			period = excluded.period,
			amount_kopecks = excluded.amount_kopecks,
			features_json = excluded.features_json,
			current_period_start = excluded.current_period_start,
			current_period_end = excluded.current_period_end,
			cancel_at_period_end = excluded.cancel_at_period_end,
			payment_method_id = excluded.payment_method_id,
			past_due_since = excluded.past_due_since,
			updated_at = excluded.updated_at
	`,
		sub.ID, sub.OwnerTelegramID, string(sub.Status), sub.PlanVersionID, string(sub.Period),
		sub.AmountKopecks, featuresJSON,
		sub.CurrentPeriodStart.UTC().Format(time.RFC3339),
		sub.CurrentPeriodEnd.UTC().Format(time.RFC3339),
		cancel, sub.PaymentMethodID, pastDue,
		sub.CreatedAt.UTC().Format(time.RFC3339),
		sub.UpdatedAt.UTC().Format(time.RFC3339),
	)
	if err != nil {
		return billing.Subscription{}, err
	}
	// Reload to get canonical id if conflict updated existing row with different id.
	return r.reloadSubscription(ctx, sub.OwnerTelegramID)
}

func (r *BillingRepository) reloadSubscription(ctx context.Context, owner int64) (billing.Subscription, error) {
	s, err := r.GetSubscriptionByOwner(ctx, owner)
	if err != nil {
		return billing.Subscription{}, err
	}
	if s == nil {
		return billing.Subscription{}, fmt.Errorf("subscription missing after save")
	}
	return *s, nil
}

// ListSubscriptionsDueForRenew returns candidates for renewal/expiry processing.
func (r *BillingRepository) ListSubscriptionsDueForRenew(ctx context.Context, now time.Time) ([]billing.Subscription, error) {
	var rows []subscriptionRow
	err := r.db.SelectContext(ctx, &rows, `
		SELECT id, owner_telegram_id, status, plan_version_id, period, amount_kopecks, features_json,
			current_period_start, current_period_end, cancel_at_period_end, payment_method_id,
			past_due_since, created_at, updated_at
		FROM billing_subscriptions
		WHERE status IN ('active', 'past_due', 'canceled')
		  AND current_period_end <= $1
	`, now.UTC().Format(time.RFC3339))
	if err != nil {
		return nil, err
	}
	out := make([]billing.Subscription, 0, len(rows))
	for _, row := range rows {
		s, err := subscriptionFromRow(row)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, nil
}

type paymentRow struct {
	ID                string `db:"id"`
	OwnerTelegramID   int64  `db:"owner_telegram_id"`
	PlanVersionID     string `db:"plan_version_id"`
	Period            string `db:"period"`
	AmountKopecks     int64  `db:"amount_kopecks"`
	Status            string `db:"status"`
	IdempotencyKey    string `db:"idempotency_key"`
	YooKassaPaymentID string `db:"yookassa_payment_id"`
	ConfirmationURL   string `db:"confirmation_url"`
	Purpose           string `db:"purpose"`
	CreatedAt         string `db:"created_at"`
	UpdatedAt         string `db:"updated_at"`
}

func paymentFromRow(row paymentRow) (billing.Payment, error) {
	created, err := time.Parse(time.RFC3339, row.CreatedAt)
	if err != nil {
		return billing.Payment{}, err
	}
	updated, err := time.Parse(time.RFC3339, row.UpdatedAt)
	if err != nil {
		return billing.Payment{}, err
	}
	return billing.Payment{
		ID:                row.ID,
		OwnerTelegramID:   row.OwnerTelegramID,
		PlanVersionID:     row.PlanVersionID,
		Period:            billing.Period(row.Period),
		AmountKopecks:     row.AmountKopecks,
		Status:            billing.PaymentStatus(row.Status),
		IdempotencyKey:    row.IdempotencyKey,
		YooKassaPaymentID: row.YooKassaPaymentID,
		ConfirmationURL:   row.ConfirmationURL,
		Purpose:           row.Purpose,
		CreatedAt:         created,
		UpdatedAt:         updated,
	}, nil
}

// CreatePayment inserts a pending payment.
func (r *BillingRepository) CreatePayment(ctx context.Context, p billing.Payment) (billing.Payment, error) {
	if p.ID == "" {
		p.ID = billingNewID()
	}
	now := time.Now().UTC()
	if p.CreatedAt.IsZero() {
		p.CreatedAt = now
	}
	p.UpdatedAt = now
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO billing_payments (
			id, owner_telegram_id, plan_version_id, period, amount_kopecks, status,
			idempotency_key, yookassa_payment_id, confirmation_url, purpose, created_at, updated_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
	`,
		p.ID, p.OwnerTelegramID, p.PlanVersionID, string(p.Period), p.AmountKopecks, string(p.Status),
		p.IdempotencyKey, p.YooKassaPaymentID, p.ConfirmationURL, p.Purpose,
		p.CreatedAt.UTC().Format(time.RFC3339), p.UpdatedAt.UTC().Format(time.RFC3339),
	)
	if err != nil {
		return billing.Payment{}, err
	}
	return p, nil
}

// UpdatePayment updates mutable payment fields.
func (r *BillingRepository) UpdatePayment(ctx context.Context, p billing.Payment) error {
	p.UpdatedAt = time.Now().UTC()
	_, err := r.db.ExecContext(ctx, `
		UPDATE billing_payments SET
			status = $2, yookassa_payment_id = $3, confirmation_url = $4, updated_at = $5
		WHERE id = $1
	`, p.ID, string(p.Status), p.YooKassaPaymentID, p.ConfirmationURL, p.UpdatedAt.Format(time.RFC3339))
	return err
}

// GetPaymentByID loads a payment.
func (r *BillingRepository) GetPaymentByID(ctx context.Context, id string) (*billing.Payment, error) {
	var row paymentRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, owner_telegram_id, plan_version_id, period, amount_kopecks, status,
			idempotency_key, yookassa_payment_id, confirmation_url, purpose, created_at, updated_at
		FROM billing_payments WHERE id = $1
	`, id)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := paymentFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// GetPaymentByYooKassaID loads by provider payment id.
func (r *BillingRepository) GetPaymentByYooKassaID(ctx context.Context, yooID string) (*billing.Payment, error) {
	if yooID == "" {
		return nil, nil
	}
	var row paymentRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, owner_telegram_id, plan_version_id, period, amount_kopecks, status,
			idempotency_key, yookassa_payment_id, confirmation_url, purpose, created_at, updated_at
		FROM billing_payments WHERE yookassa_payment_id = $1
	`, yooID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := paymentFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// GetPaymentByIdempotencyKey finds an existing payment for retries.
func (r *BillingRepository) GetPaymentByIdempotencyKey(ctx context.Context, key string) (*billing.Payment, error) {
	var row paymentRow
	err := r.db.GetContext(ctx, &row, `
		SELECT id, owner_telegram_id, plan_version_id, period, amount_kopecks, status,
			idempotency_key, yookassa_payment_id, confirmation_url, purpose, created_at, updated_at
		FROM billing_payments WHERE idempotency_key = $1
	`, key)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	p, err := paymentFromRow(row)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// AddLedgerEntry appends a ledger row.
func (r *BillingRepository) AddLedgerEntry(ctx context.Context, e billing.LedgerEntry) (billing.LedgerEntry, error) {
	if e.ID == "" {
		e.ID = billingNewID()
	}
	if e.CreatedAt.IsZero() {
		e.CreatedAt = time.Now().UTC()
	}
	_, err := r.db.ExecContext(ctx, `
		INSERT INTO billing_ledger (id, owner_telegram_id, kind, amount_kopecks, reason, payment_id, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7)
	`, e.ID, e.OwnerTelegramID, string(e.Kind), e.AmountKopecks, e.Reason, e.PaymentID, e.CreatedAt.UTC().Format(time.RFC3339))
	if err != nil {
		return billing.LedgerEntry{}, err
	}
	return e, nil
}

// ListLedger returns newest-first ledger entries for owner.
func (r *BillingRepository) ListLedger(ctx context.Context, ownerTelegramID int64, limit int) ([]billing.LedgerEntry, error) {
	if limit <= 0 {
		limit = 50
	}
	type ledgerRow struct {
		ID              string `db:"id"`
		OwnerTelegramID int64  `db:"owner_telegram_id"`
		Kind            string `db:"kind"`
		AmountKopecks   int64  `db:"amount_kopecks"`
		Reason          string `db:"reason"`
		PaymentID       string `db:"payment_id"`
		CreatedAt       string `db:"created_at"`
	}
	var rows []ledgerRow
	err := r.db.SelectContext(ctx, &rows, `
		SELECT id, owner_telegram_id, kind, amount_kopecks, reason, payment_id, created_at
		FROM billing_ledger WHERE owner_telegram_id = $1
		ORDER BY created_at DESC LIMIT $2
	`, ownerTelegramID, limit)
	if err != nil {
		return nil, err
	}
	out := make([]billing.LedgerEntry, 0, len(rows))
	for _, row := range rows {
		created, err := time.Parse(time.RFC3339, row.CreatedAt)
		if err != nil {
			return nil, err
		}
		out = append(out, billing.LedgerEntry{
			ID:              row.ID,
			OwnerTelegramID: row.OwnerTelegramID,
			Kind:            billing.LedgerEntryKind(row.Kind),
			AmountKopecks:   row.AmountKopecks,
			Reason:          row.Reason,
			PaymentID:       row.PaymentID,
			CreatedAt:       created,
		})
	}
	return out, nil
}
