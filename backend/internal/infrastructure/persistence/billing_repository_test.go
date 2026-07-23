package persistence_test

import (
	"context"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/billing"
	"github.com/tonatos/bond-monitor/backend/internal/infrastructure/persistence"
)

func TestBillingRepository_SeedAndSubscription(t *testing.T) {
	db, err := persistence.Open("sqlite://" + t.TempDir() + "/test.db")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := persistence.ApplyMigrations(db.DB, "sqlite", ""); err != nil {
		t.Fatal(err)
	}
	repo := persistence.NewBillingRepository(db)
	ctx := context.Background()

	plans, err := repo.ListCurrentPlanVersions(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(plans) != 2 {
		t.Fatalf("expected 2 current plans, got %d", len(plans))
	}

	month, err := repo.GetCurrentPlanByPeriod(ctx, billing.PeriodMonth)
	if err != nil || month == nil {
		t.Fatalf("month plan: %v %#v", err, month)
	}
	if month.AmountKopecks != 79500 {
		t.Fatalf("month price %d", month.AmountKopecks)
	}

	now := time.Date(2026, 7, 1, 12, 0, 0, 0, time.UTC)
	sub := billing.ApplySuccessfulPayment(nil, *month, 42, "checkout", now, "pm_test")
	saved, err := repo.SaveSubscription(ctx, sub)
	if err != nil {
		t.Fatal(err)
	}
	got, err := repo.GetSubscriptionByOwner(ctx, 42)
	if err != nil || got == nil {
		t.Fatalf("get: %v", err)
	}
	if got.ID != saved.ID || got.AmountKopecks != 79500 {
		t.Fatalf("unexpected sub %#v", got)
	}

	pay, err := repo.CreatePayment(ctx, billing.Payment{
		OwnerTelegramID: 42,
		PlanVersionID:   month.ID,
		Period:          billing.PeriodMonth,
		AmountKopecks:   month.AmountKopecks,
		Status:          billing.PaymentPending,
		IdempotencyKey:  "idem-1",
		Purpose:         "checkout",
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = repo.AddLedgerEntry(ctx, billing.LedgerEntry{
		OwnerTelegramID: 42,
		Kind:            billing.LedgerDebit,
		AmountKopecks:   pay.AmountKopecks,
		Reason:          "subscription_month",
		PaymentID:       pay.ID,
	})
	if err != nil {
		t.Fatal(err)
	}
	ledger, err := repo.ListLedger(ctx, 42, 10)
	if err != nil || len(ledger) != 1 {
		t.Fatalf("ledger: %v len=%d", err, len(ledger))
	}
}
