package notifications_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	devnotify "github.com/tonatos/instrumenta/backend/internal/dev/notifications"
	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/notifications"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading/testutil"
)

func adoptedPosition(isin, figi string, today time.Time) portfolio.PortfolioPosition {
	maturity := today.Add(500 * 24 * time.Hour)
	rate := 12.0
	period := 30
	return portfolio.PortfolioPosition{
		ISIN: isin, Secid: isin, Name: "Hold Bond", Lots: 2, LotSize: 1,
		PurchaseCleanPricePct: 99, PurchaseDirtyPriceRub: 990, PurchaseACIRub: 0,
		PurchaseDate: today.Add(-30 * 24 * time.Hour), PurchaseAmountRub: 1_980,
		CouponRate: &rate, FaceValue: 1000, MaturityDate: &maturity,
		CouponPeriodDays: &period, Source: portfolio.PositionSourceAdopted, FIGI: bonds.StrPtr(figi),
	}
}

func TestApplyDevOverridesPutOfferTriggersAlert(t *testing.T) {
	today := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	isin := "RU000PO"
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.ID = "p1" })
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = isin, "Put Bond", "FIGI-PO"
	})
	position := adoptedPosition(isin, "FIGI-PO", today)
	path := filepath.Join(t.TempDir(), "overrides.json")

	if err := devnotify.SaveDevOverrides(path, devnotify.BuildPutOfferOverrides("p1", isin, today)); err != nil {
		t.Fatal(err)
	}
	universe := []bonds.BondRecord{bond}
	positions := []portfolio.PortfolioPosition{position}
	if !devnotify.ApplyDevNotificationOverrides(&p, universe, positions, "p1", path, today) {
		t.Fatal("expected overrides to apply")
	}

	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: p,
		Holdings:  []notifications.HoldingSnapshot{{ISIN: isin, FIGI: "FIGI-PO", Lots: 2}},
		Positions: positions,
		Universe:  universe,
		Today:     today,
		KeyRatePP: 16, TaxRateFraction: 0.13,
		Rules:     notifications.WorkerAlertRules,
	})
	var putAlerts []notifications.Alert
	for _, a := range alerts {
		if a.Kind == notifications.AlertKindPutOfferAction {
			putAlerts = append(putAlerts, a)
		}
	}
	if len(putAlerts) != 1 {
		t.Fatalf("expected 1 put offer alert, got %d", len(putAlerts))
	}
	if putAlerts[0].ISIN != isin {
		t.Fatalf("unexpected isin %s", putAlerts[0].ISIN)
	}
}

func TestApplyDevOverridesRiskDefaultTriggersCritical(t *testing.T) {
	isin := "RU000DEF"
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.ID = "p-def" })
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = isin, "Default Bond", "FIGI-D"
	})
	path := filepath.Join(t.TempDir(), "overrides.json")

	if err := devnotify.SaveDevOverrides(path, devnotify.BuildRiskDefaultOverrides("p-def", isin)); err != nil {
		t.Fatal(err)
	}
	universe := []bonds.BondRecord{bond}
	if !devnotify.ApplyDevNotificationOverrides(&p, universe, nil, "p-def", path, time.Now()) {
		t.Fatal("expected overrides to apply")
	}

	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: p,
		Holdings:  []notifications.HoldingSnapshot{{ISIN: isin, FIGI: "FIGI-D", Lots: 2}},
		Universe:  universe,
		Today:     time.Now(),
		KeyRatePP: 16, TaxRateFraction: 0.13,
		Rules:     notifications.WorkerAlertRules,
	})
	var riskAlerts []notifications.Alert
	for _, a := range alerts {
		if a.Kind == notifications.AlertKindRiskEscalation {
			riskAlerts = append(riskAlerts, a)
		}
	}
	if len(riskAlerts) != 1 {
		t.Fatalf("expected 1 risk alert, got %d", len(riskAlerts))
	}
	if riskAlerts[0].Urgency != notifications.AlertUrgencyCritical {
		t.Fatalf("expected critical, got %s", riskAlerts[0].Urgency)
	}
}

func TestLoadDevOverridesIgnoresOtherPortfolio(t *testing.T) {
	path := filepath.Join(t.TempDir(), "overrides.json")
	raw, _ := json.Marshal(map[string]any{
		"portfolio_id":   "other",
		"put_offers":     map[string]any{},
		"risk_baselines": map[string]any{},
		"bond_risk":      map[string]any{},
	})
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	if devnotify.LoadDevOverrides(path, "p1") != nil {
		t.Fatal("expected nil for portfolio mismatch")
	}
}

func TestApplyDevOverridesSkipsWhenPortfolioMismatch(t *testing.T) {
	today := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	isin := "RU000PO"
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.ID = "p1" })
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = isin, "FIGI-PO"
	})
	position := adoptedPosition(isin, "FIGI-PO", today)
	path := filepath.Join(t.TempDir(), "overrides.json")

	if err := devnotify.SaveDevOverrides(path, devnotify.BuildPutOfferOverrides("other", isin, today)); err != nil {
		t.Fatal(err)
	}
	if devnotify.ApplyDevNotificationOverrides(&p, []bonds.BondRecord{bond}, []portfolio.PortfolioPosition{position}, "p1", path, today) {
		t.Fatal("expected overrides to be skipped")
	}
	if bond.OfferDate != nil {
		t.Fatal("expected bond offer_date to remain unset")
	}
}
