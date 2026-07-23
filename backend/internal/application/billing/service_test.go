package billing_test

import (
	"context"
	"testing"
	"time"

	appbilling "github.com/tonatos/instrumenta/backend/internal/application/billing"
	"github.com/tonatos/instrumenta/backend/internal/domain/billing"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/persistence"
	"github.com/tonatos/instrumenta/backend/internal/infrastructure/yookassa"
)

type memGateway struct {
	enabled bool
	create  func(ctx context.Context, req yookassa.CreatePaymentRequest) (yookassa.CreatePaymentResult, error)
	get     func(ctx context.Context, id string) (yookassa.PaymentInfo, error)
}

func (m *memGateway) Enabled() bool { return m.enabled }

func (m *memGateway) CreatePayment(ctx context.Context, req yookassa.CreatePaymentRequest) (yookassa.CreatePaymentResult, error) {
	return m.create(ctx, req)
}

func (m *memGateway) GetPayment(ctx context.Context, id string) (yookassa.PaymentInfo, error) {
	return m.get(ctx, id)
}

func setupBilling(t *testing.T, complimentary []int64, gw yookassa.PaymentGateway) (*appbilling.Service, *persistence.BillingRepository) {
	t.Helper()
	db, err := persistence.Open("sqlite://" + t.TempDir() + "/b.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatal(err)
	}
	repo := persistence.NewBillingRepository(db)
	svc := appbilling.NewService(repo, gw, complimentary, "http://localhost/account/plan")
	return svc, repo
}

func TestRequireFeature_Complimentary(t *testing.T) {
	svc, _ := setupBilling(t, []int64{42}, yookassa.DisabledGateway{})
	if err := svc.RequireFeature(context.Background(), 42, billing.FeaturePortfolioAttach); err != nil {
		t.Fatal(err)
	}
	if err := svc.RequireFeature(context.Background(), 1, billing.FeaturePortfolioAttach); err != appbilling.ErrSubscriptionRequired {
		t.Fatalf("got %v", err)
	}
}

func TestCheckout_DisabledGateway(t *testing.T) {
	svc, _ := setupBilling(t, nil, yookassa.DisabledGateway{})
	_, err := svc.CreateCheckout(context.Background(), 7, billing.PeriodMonth, "checkout")
	if err != appbilling.ErrPaymentUnavailable {
		t.Fatalf("got %v", err)
	}
}

func TestWebhook_IdempotentActivate(t *testing.T) {
	var stored yookassa.PaymentInfo
	gw := &memGateway{
		enabled: true,
		create: func(_ context.Context, req yookassa.CreatePaymentRequest) (yookassa.CreatePaymentResult, error) {
			return yookassa.CreatePaymentResult{
				ID:              "yoo_1",
				Status:          "pending",
				ConfirmationURL: "https://pay.example/1",
			}, nil
		},
		get: func(_ context.Context, id string) (yookassa.PaymentInfo, error) {
			return stored, nil
		},
	}
	svc, repo := setupBilling(t, nil, gw)
	ctx := context.Background()
	res, err := svc.CreateCheckout(ctx, 9, billing.PeriodMonth, "checkout")
	if err != nil {
		t.Fatal(err)
	}
	pay, err := repo.GetPaymentByID(ctx, res.PaymentID)
	if err != nil || pay == nil {
		t.Fatal(err)
	}
	stored = yookassa.PaymentInfo{
		ID:            "yoo_1",
		Status:        "succeeded",
		Paid:          true,
		AmountKopecks: pay.AmountKopecks,
		PaymentMethodID: "pm_saved",
		Metadata: map[string]string{
			"owner_telegram_id": "9",
			"payment_id":        pay.ID,
		},
	}
	if err := svc.HandleYooKassaWebhook(ctx, "yoo_1"); err != nil {
		t.Fatal(err)
	}
	if err := svc.HandleYooKassaWebhook(ctx, "yoo_1"); err != nil {
		t.Fatal(err)
	}
	if err := svc.RequireFeature(ctx, 9, billing.FeatureBrokerCredentialsWrite); err != nil {
		t.Fatal(err)
	}
	sub, err := repo.GetSubscriptionByOwner(ctx, 9)
	if err != nil || sub == nil || sub.PaymentMethodID != "pm_saved" {
		t.Fatalf("sub %#v err %v", sub, err)
	}
	ledger, err := repo.ListLedger(ctx, 9, 10)
	if err != nil || len(ledger) != 1 {
		t.Fatalf("ledger len=%d err=%v", len(ledger), err)
	}
}

func TestRenew_GrandfatheredAmount(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	gw := &memGateway{
		enabled: true,
		create: func(_ context.Context, req yookassa.CreatePaymentRequest) (yookassa.CreatePaymentResult, error) {
			if req.AmountKopecks != 50000 {
				t.Fatalf("expected grandfathered 50000, got %d", req.AmountKopecks)
			}
			return yookassa.CreatePaymentResult{ID: "yoo_r", Status: "succeeded", Paid: true, PaymentMethodID: "pm"}, nil
		},
		get: func(context.Context, string) (yookassa.PaymentInfo, error) {
			return yookassa.PaymentInfo{}, nil
		},
	}
	svc, repo := setupBilling(t, nil, gw)
	ctx := context.Background()
	_, err := repo.SaveSubscription(ctx, billing.Subscription{
		OwnerTelegramID:    3,
		Status:             billing.StatusActive,
		PlanVersionID:      "pro_month_v1",
		Period:             billing.PeriodMonth,
		AmountKopecks:      50000,
		Features:           billing.PaidFeaturesV1(),
		CurrentPeriodStart: now.Add(-30 * 24 * time.Hour),
		CurrentPeriodEnd:   now,
		PaymentMethodID:    "pm",
		CreatedAt:          now,
		UpdatedAt:          now,
	})
	if err != nil {
		t.Fatal(err)
	}
	renewed, failed, _, err := svc.RenewDue(ctx, now)
	if err != nil || failed != 0 || renewed != 1 {
		t.Fatalf("renewed=%d failed=%d err=%v", renewed, failed, err)
	}
}
