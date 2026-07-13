package notifications_test

import (
	"strings"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/notifications"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading/testutil"
)

func holdingSnapshot(isin, figi string, lots int) notifications.HoldingSnapshot {
	price := 96.0
	return notifications.HoldingSnapshot{
		ISIN: isin, FIGI: figi, Name: "Hold Bond", Lots: lots, CurrentPricePct: &price,
	}
}

func putPosition(today time.Time) portfolio.PortfolioPosition {
	offerDate := today.Add(10 * 24 * time.Hour)
	start := today.Add(-5 * 24 * time.Hour)
	end := offerDate.Add(-24 * time.Hour)
	maturity := today.Add(500 * 24 * time.Hour)
	offerPrice := 100.0
	rate := 12.0
	period := 30
	return portfolio.PortfolioPosition{
		ISIN: "RU000PO", Secid: "RU000PO", Name: "Put Offer Bond", Lots: 2, LotSize: 1,
		PurchaseCleanPricePct: 99, PurchaseDirtyPriceRub: 990, PurchaseACIRub: 0,
		PurchaseDate: today.Add(-30 * 24 * time.Hour), PurchaseAmountRub: 1_980,
		CouponRate: &rate, FaceValue: 1000, MaturityDate: &maturity, OfferDate: &offerDate,
		OfferSubmissionStart: &start, OfferSubmissionEnd: &end, OfferPricePct: &offerPrice,
		CouponPeriodDays: &period, Source: portfolio.PositionSourceAdopted, FIGI: bonds.StrPtr("FIGI-PO"),
		PutOfferDecision: bonds.PutOfferPending,
	}
}

func TestCollectAlertsPutOfferActionWhenWindowOpen(t *testing.T) {
	today := time.Date(2026, 7, 28, 0, 0, 0, 0, time.UTC)
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.ID = "p1" })
	position := putPosition(today)
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = position.ISIN, position.Name, "FIGI-PO"
		b.MaturityDate = position.MaturityDate
		b.OfferDate = position.OfferDate
		b.OfferSubmissionStart = position.OfferSubmissionStart
		b.OfferSubmissionEnd = position.OfferSubmissionEnd
		b.OfferPricePct = position.OfferPricePct
	})
	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: p,
		Holdings:  []notifications.HoldingSnapshot{{ISIN: position.ISIN, FIGI: "FIGI-PO", Lots: 2}},
		Positions: []portfolio.PortfolioPosition{position},
		Universe:  []bonds.BondRecord{bond},
		Today:     today,
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
	if putAlerts[0].ISIN != position.ISIN {
		t.Fatalf("unexpected isin %s", putAlerts[0].ISIN)
	}
	if putAlerts[0].Urgency != notifications.AlertUrgencySoon && putAlerts[0].Urgency != notifications.AlertUrgencyCritical {
		t.Fatalf("unexpected urgency %s", putAlerts[0].Urgency)
	}
	if putAlerts[0].ChatTemplate == nil {
		t.Fatal("expected chat template")
	}
}

func TestCollectAlertsNoPutOfferWhenWindowNotOpen(t *testing.T) {
	today := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	offerDate := time.Date(2026, 8, 7, 0, 0, 0, 0, time.UTC)
	maturity := time.Date(2027, 7, 30, 0, 0, 0, 0, time.UTC)
	offerPrice := 100.0
	rate := 12.0
	period := 91
	position := portfolio.PortfolioPosition{
		ISIN: "RU000A109874", Secid: "RU000A109874", Name: "СамолетP15", Lots: 10, LotSize: 1,
		PurchaseCleanPricePct: 99, PurchaseDirtyPriceRub: 990, PurchaseACIRub: 0,
		PurchaseDate: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), PurchaseAmountRub: 99_000,
		CouponRate: &rate, FaceValue: 1000, MaturityDate: &maturity, OfferDate: &offerDate,
		OfferPricePct: &offerPrice, CouponPeriodDays: &period, Source: portfolio.PositionSourceAdopted,
		FIGI: bonds.StrPtr("FIGI-SAM"),
	}
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = position.ISIN, position.Name, "FIGI-SAM"
		b.MaturityDate = &maturity
		b.OfferDate = &offerDate
		b.OfferPricePct = &offerPrice
	})
	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: testutil.MakePortfolio(),
		Holdings:  []notifications.HoldingSnapshot{{ISIN: position.ISIN, FIGI: "FIGI-SAM", Lots: 10}},
		Positions: []portfolio.PortfolioPosition{position},
		Universe:  []bonds.BondRecord{bond},
		Today:     today,
	})
	for _, a := range alerts {
		if a.Kind == notifications.AlertKindPutOfferAction || a.Kind == notifications.AlertKindPutOfferWatch {
			t.Fatalf("unexpected alert kind %s", a.Kind)
		}
	}
}

func TestCollectAlertsRiskEscalation(t *testing.T) {
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.ID = "p-risk" })
	isin := "RU000RISK"
	p.RiskBaselines[isin] = portfolio.RiskSnapshot{CreditRating: bonds.StrPtr("ruBBB-")}
	rating := "ruBB+"
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = isin, "Risk Bond", "FIGI-R"
		b.CreditRating = &rating
	})
	price := 96.0
	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: p,
		Holdings:  []notifications.HoldingSnapshot{{ISIN: isin, FIGI: "FIGI-R", Lots: 2, CurrentPricePct: &price}},
		Universe:  []bonds.BondRecord{bond},
		Today:     time.Now(),
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
	if riskAlerts[0].Urgency != notifications.AlertUrgencySoon || !riskAlerts[0].RiskAcknowledgeable {
		t.Fatalf("unexpected risk alert: %+v", riskAlerts[0])
	}
	reason := strings.ToLower(riskAlerts[0].Reason)
	if !strings.Contains(reason, "investment grade") && !strings.Contains(reason, "рейтинг") {
		t.Fatalf("unexpected reason: %s", riskAlerts[0].Reason)
	}
}

func TestCollectAlertsRiskCriticalDefault(t *testing.T) {
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.ID = "p-def" })
	isin := "RU000DEF"
	p.RiskBaselines[isin] = portfolio.RiskSnapshot{CreditRating: bonds.StrPtr("ruBBB")}
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = isin, "Default Bond", "FIGI-D"
		b.HasDefault = true
	})
	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: p,
		Holdings:  []notifications.HoldingSnapshot{{ISIN: isin, FIGI: "FIGI-D", Lots: 2}},
		Universe:  []bonds.BondRecord{bond},
		Today:     time.Now(),
	})
	for _, a := range alerts {
		if a.Kind == notifications.AlertKindRiskEscalation {
			if a.Urgency != notifications.AlertUrgencyCritical {
				t.Fatalf("expected critical, got %s", a.Urgency)
			}
			return
		}
	}
	t.Fatal("expected risk escalation alert")
}

func TestCollectAlertsPutOfferSkippedWhenHoldDecision(t *testing.T) {
	today := time.Date(2026, 7, 28, 0, 0, 0, 0, time.UTC)
	position := putPosition(today)
	position.PutOfferDecision = bonds.PutOfferHold
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = position.ISIN, "FIGI-PO"
		b.MaturityDate = position.MaturityDate
		b.OfferDate = position.OfferDate
		b.OfferSubmissionStart = position.OfferSubmissionStart
		b.OfferSubmissionEnd = position.OfferSubmissionEnd
		b.OfferPricePct = position.OfferPricePct
	})
	alerts := notifications.CollectAlerts(notifications.AlertParams{
		Portfolio: testutil.MakePortfolio(),
		Holdings:  []notifications.HoldingSnapshot{{ISIN: position.ISIN, FIGI: "FIGI-PO", Lots: 2}},
		Positions: []portfolio.PortfolioPosition{position},
		Universe:  []bonds.BondRecord{bond},
		Today:     today,
	})
	for _, a := range alerts {
		if a.Kind == notifications.AlertKindPutOfferAction {
			t.Fatal("expected no put offer action when hold")
		}
	}
}

func TestHoldingSnapshotUnusedFields(t *testing.T) {
	_ = holdingSnapshot("RU000A1", "FIGI-1", 2)
}
