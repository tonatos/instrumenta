package billing

import (
	"testing"
	"time"
)

func TestHasAccess_Complimentary(t *testing.T) {
	if !HasAccess(AccessInput{Complimentary: true}, FeaturePortfolioAttach) {
		t.Fatal("complimentary must grant all paid features")
	}
}

func TestHasAccess_NoSubscription(t *testing.T) {
	if HasAccess(AccessInput{}, FeatureBrokerCredentialsWrite) {
		t.Fatal("expected deny without subscription")
	}
}

func TestHasAccess_ActiveWithinPeriod(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	sub := &Subscription{
		Status:           StatusActive,
		Features:         PaidFeaturesV1(),
		CurrentPeriodEnd: now.Add(24 * time.Hour),
	}
	if !HasAccess(AccessInput{Subscription: sub, Now: now}, FeatureTradingPortfolioAccess) {
		t.Fatal("expected access")
	}
}

func TestHasAccess_ActiveExpiredPeriod(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	sub := &Subscription{
		Status:           StatusActive,
		Features:         PaidFeaturesV1(),
		CurrentPeriodEnd: now.Add(-time.Hour),
	}
	if HasAccess(AccessInput{Subscription: sub, Now: now}, FeaturePortfolioAttach) {
		t.Fatal("expected deny after period end")
	}
}

func TestHasAccess_CanceledStillInPeriod(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	sub := &Subscription{
		Status:            StatusCanceled,
		CancelAtPeriodEnd: true,
		Features:          PaidFeaturesV1(),
		CurrentPeriodEnd:  now.Add(48 * time.Hour),
	}
	if !HasAccess(AccessInput{Subscription: sub, Now: now}, FeatureBrokerCredentialsWrite) {
		t.Fatal("canceled but paid period should still work")
	}
}

func TestHasAccess_PastDueWithinGrace(t *testing.T) {
	now := time.Date(2026, 7, 2, 0, 0, 0, 0, time.UTC)
	pastDue := now.Add(-24 * time.Hour)
	sub := &Subscription{
		Status:           StatusPastDue,
		Features:         PaidFeaturesV1(),
		CurrentPeriodEnd: pastDue,
		PastDueSince:     &pastDue,
	}
	if !HasAccess(AccessInput{Subscription: sub, Now: now, Policy: DefaultPolicy()}, FeaturePortfolioAttach) {
		t.Fatal("expected grace access")
	}
}

func TestHasAccess_PastDueAfterGrace(t *testing.T) {
	now := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	pastDue := now.Add(-10 * 24 * time.Hour)
	sub := &Subscription{
		Status:           StatusPastDue,
		Features:         PaidFeaturesV1(),
		CurrentPeriodEnd: pastDue,
		PastDueSince:     &pastDue,
	}
	if HasAccess(AccessInput{Subscription: sub, Now: now, Policy: DefaultPolicy()}, FeaturePortfolioAttach) {
		t.Fatal("expected deny after grace")
	}
}

func TestApplySuccessfulPayment_GrandfatherOnRenew(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	oldFeatures := []Feature{FeaturePortfolioAttach}
	sub := &Subscription{
		Status:           StatusActive,
		PlanVersionID:    "old",
		Period:           PeriodMonth,
		AmountKopecks:    50000,
		Features:         oldFeatures,
		CurrentPeriodEnd: now,
		PaymentMethodID:  "pm_1",
	}
	newPlan := PlanVersion{
		ID:            "new",
		Period:        PeriodMonth,
		AmountKopecks: 79500,
		Features:      PaidFeaturesV1(),
	}
	out := ApplySuccessfulPayment(sub, newPlan, 1, "renew", now, "pm_1")
	if out.AmountKopecks != 50000 {
		t.Fatalf("renew must keep grandfathered price, got %d", out.AmountKopecks)
	}
	if len(out.Features) != 1 || out.Features[0] != FeaturePortfolioAttach {
		t.Fatalf("renew must keep grandfathered features: %#v", out.Features)
	}
	if !out.CurrentPeriodEnd.Equal(now.Add(PeriodDuration(PeriodMonth))) {
		t.Fatalf("unexpected period end %v", out.CurrentPeriodEnd)
	}
}

func TestApplySuccessfulPayment_ChangePeriodAdoptsNewPlan(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	sub := &Subscription{
		Status:        StatusActive,
		Period:        PeriodMonth,
		AmountKopecks: 79500,
		Features:      PaidFeaturesV1(),
	}
	year := PlanVersion{
		ID:            "pro_year",
		Period:        PeriodYear,
		AmountKopecks: 594000,
		Features:      PaidFeaturesV1(),
	}
	out := ApplySuccessfulPayment(sub, year, 1, "change_period", now, "pm_2")
	if out.Period != PeriodYear || out.AmountKopecks != 594000 {
		t.Fatalf("change_period must adopt yearly plan: %#v", out)
	}
}

func TestYearlySavings(t *testing.T) {
	// 795*12 = 9540; year 5940; savings 3600 ≈ 37.7%
	s := YearlySavingsKopecks(79500, 594000)
	if s != 360000 {
		t.Fatalf("savings kopecks: got %d", s)
	}
	pct := YearlySavingsPercent(79500, 594000)
	if pct < 37.7 || pct > 37.8 {
		t.Fatalf("savings percent: got %v", pct)
	}
}

func TestShouldAttemptRenew(t *testing.T) {
	now := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	sub := Subscription{
		Status:            StatusActive,
		PaymentMethodID:   "pm",
		CurrentPeriodEnd:  now,
		CancelAtPeriodEnd: false,
	}
	if !ShouldAttemptRenew(sub, now) {
		t.Fatal("expected renew")
	}
	sub.CancelAtPeriodEnd = true
	if ShouldAttemptRenew(sub, now) {
		t.Fatal("cancel_at_period_end must skip renew")
	}
}
