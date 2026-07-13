package trading_test

import (
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading"
	"github.com/tonatos/bond-monitor/backend/internal/domain/trading/testutil"
)

func makeSessionWithBuyItems(portfolioID string) trading.DeploySession {
	now := time.Now().UTC()
	price1, price2 := 100.5, 101.0
	return trading.DeploySession{
		ID: "sess-1", PortfolioID: portfolioID, Status: trading.DeploySessionActive,
		Items: []trading.DeploySessionItem{
			{ID: "item-1", Kind: trading.DeploySessionItemBuy, ISIN: "RU000A1", Name: "Bond A", Lots: 5,
				FIGI: bonds.StrPtr("FIGI-A"), SuggestedPricePct: price1, EstimatedAmountRub: 50_000, Reason: "buy 1", Status: trading.ItemStatusPending},
			{ID: "item-2", Kind: trading.DeploySessionItemBuy, ISIN: "RU000A2", Name: "Bond B", Lots: 3,
				FIGI: bonds.StrPtr("FIGI-B"), SuggestedPricePct: price2, EstimatedAmountRub: 30_000, Reason: "buy 2", Status: trading.ItemStatusPending},
		},
		CashSnapshotRub: 100_000, CreatedAt: now, ExpiresAt: now.Add(24 * time.Hour),
	}
}

func TestBuildDeploySessionPlanIncludesBuyAndReinvest(t *testing.T) {
	today := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	maturitySoon := today
	price := 98.0
	vol := 5_000_000.0
	buyBond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000BUY1", "Buy pick", "FIGI-BUY"
		b.MaturityDate = bonds.TimePtr(time.Date(2027, 6, 1, 0, 0, 0, 0, time.UTC))
		b.LastPrice, b.VolumeRub = &price, &vol
	})
	reinvestSource := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000SRC1", "Maturing", "FIGI-SRC"
		b.MaturityDate = &maturitySoon
		p := 100.0
		b.LastPrice = &p
	})
	replacement := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000NEW1", "Replacement", "FIGI-NEW"
		b.MaturityDate = bonds.TimePtr(time.Date(2027, 9, 1, 0, 0, 0, 0, time.UTC))
		p := 99.0
		b.LastPrice, b.VolumeRub = &p, &vol
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.ID = "portfolio-1"
		p.InitialAmountRub = 200_000
		p.HorizonDate = time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC)
		p.APITradeOnly = false
	})
	snapshot := testutil.MakeAccountSnapshot(80_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-SRC"] = testutil.BondPosition("FIGI-SRC", 10, 10)
	})
	holdings := trading.BuildHoldings(snapshot, []bonds.BondRecord{reinvestSource, buyBond, replacement})
	positions := trading.EffectiveTradingPositions(p, snapshot, []bonds.BondRecord{reinvestSource, buyBond, replacement}, today)
	now := time.Date(2026, 7, 10, 12, 0, 0, 0, time.UTC)
	session := trading.BuildDeploySessionPlan(
		p, holdings, positions, []bonds.BondRecord{buyBond, reinvestSource, replacement},
		80_000, today, 16, 0.13,
		portfolio.DefaultBondSelectionPolicy, portfolio.DefaultPlanningPolicy, portfolio.DefaultDurationPolicy,
		trading.DefaultDeploySessionPolicy(), &now, nil,
	)
	kinds := map[trading.DeploySessionItemKind]bool{}
	for _, item := range session.Items {
		kinds[item.Kind] = true
		if item.Status != trading.ItemStatusPending {
			t.Fatalf("expected pending item, got %s", item.Status)
		}
	}
	if !kinds[trading.DeploySessionItemBuy] || !kinds[trading.DeploySessionItemReinvest] {
		t.Fatalf("expected buy and reinvest kinds, got %v", kinds)
	}
	if session.CashSnapshotRub != 80_000 || len(session.Items) < 1 {
		t.Fatalf("unexpected session: %+v", session)
	}
}

func TestSessionItemsToSuggestionsOnlyPending(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	orderID := "ord-1"
	session.Items[0].Status = trading.ItemStatusPlaced
	session.Items[0].OrderID = &orderID
	universe := []bonds.BondRecord{
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN, b.FIGI = "RU000A1", "FIGI-A" }),
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN, b.FIGI = "RU000A2", "FIGI-B" }),
	}
	suggestions := trading.SessionItemsToSuggestions(session, universe, map[trading.DeploySessionItemKind]bool{trading.DeploySessionItemBuy: true})
	if len(suggestions) != 1 || suggestions[0].ISIN != "RU000A2" || suggestions[0].ID != "item-2" || suggestions[0].Lots != 3 {
		t.Fatalf("unexpected suggestions: %+v", suggestions)
	}
}

func TestMarkItemPlacedPreservesRemainingItems(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	updated := trading.MarkItemPlaced(session, "item-1", "order-123")
	var pending int
	for _, item := range updated.Items {
		if item.Status == trading.ItemStatusPending {
			pending++
			if item.ISIN != "RU000A2" || item.Lots != 3 {
				t.Fatalf("unexpected pending item: %+v", item)
			}
		}
		if item.ID == "item-1" {
			if item.Status != trading.ItemStatusPlaced || item.OrderID == nil || *item.OrderID != "order-123" {
				t.Fatalf("unexpected placed item: %+v", item)
			}
		}
	}
	if pending != 1 || updated.Status != trading.DeploySessionActive {
		t.Fatalf("unexpected session state: pending=%d status=%s", pending, updated.Status)
	}
}

func TestCompleteSessionWhenAllItemsPlaced(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	session = trading.MarkItemPlaced(session, "item-1", "order-1")
	session = trading.MarkItemPlaced(session, "item-2", "order-2")
	if session.Status != trading.DeploySessionCompleted {
		t.Fatalf("expected completed, got %s", session.Status)
	}
	for _, item := range session.Items {
		if item.Status != trading.ItemStatusPlaced {
			t.Fatalf("expected all placed")
		}
	}
}

func TestCompleteSessionIfNoPendingOnAllSkipped(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	session.Items[0].Status = trading.ItemStatusSkipped
	session.Items[1].Status = trading.ItemStatusSkipped
	completed := trading.CompleteSessionIfNoPending(session)
	if completed.Status != trading.DeploySessionCompleted {
		t.Fatalf("expected completed, got %s", completed.Status)
	}
}

func TestAdviseUsesFrozenSessionAndKeepsAlertsLive(t *testing.T) {
	today := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	price := 100.0
	vol := 5_000_000.0
	bondA := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = "RU000A1", "FIGI-A"
		b.LastPrice, b.VolumeRub = &price, &vol
	})
	bondB := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = "RU000A2", "FIGI-B"
		b.LastPrice, b.VolumeRub = &price, &vol
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.ID = "p-advise"
		p.InitialAmountRub = 100_000
		p.HorizonDate = time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC)
	})
	snapshot := testutil.MakeAccountSnapshot(50_000)
	session := makeSessionWithBuyItems(p.ID)
	advice := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bondA, bondB}, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13, Today: &today, ActiveSession: &session,
	})
	var buyISINs []string
	for _, s := range advice.Suggestions {
		if s.Kind == trading.SuggestionKindBuy {
			buyISINs = append(buyISINs, s.ISIN)
		}
	}
	if len(buyISINs) != 2 || buyISINs[0] != "RU000A1" || buyISINs[1] != "RU000A2" {
		t.Fatalf("unexpected buy isins: %v", buyISINs)
	}
	if advice.DeploySession == nil || advice.DeploySession.ID != "sess-1" {
		t.Fatal("expected frozen session in advice")
	}
	sessionAfter := trading.MarkItemPlaced(session, "item-1", "ord-1")
	advicePartial := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bondA, bondB}, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13, Today: &today, ActiveSession: &sessionAfter,
	})
	var partialISINs []string
	for _, s := range advicePartial.Suggestions {
		if s.Kind == trading.SuggestionKindBuy {
			partialISINs = append(partialISINs, s.ISIN)
		}
	}
	if len(partialISINs) != 1 || partialISINs[0] != "RU000A2" || advicePartial.Suggestions[0].Lots != 3 {
		t.Fatalf("unexpected partial buys: %+v", advicePartial.Suggestions)
	}
}

func TestSyncSessionMarksFilledOnTerminalOrder(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	session = trading.MarkItemPlaced(session, "item-1", "ord-fill")
	price := 100.5
	total := 50_000.0
	orders := []trading.BrokerActiveOrder{{
		OrderID: "ord-fill", RequestUID: "uid", FIGI: "FIGI-A", Direction: "BUY",
		LotsRequested: 5, LotsExecuted: 5, Status: "EXECUTION_REPORT_STATUS_FILL",
		PricePct: &price, TotalOrderAmountRub: &total,
	}}
	synced := trading.SyncSessionWithOrders(session, orders)
	for _, item := range synced.Items {
		if item.ID == "item-1" && item.Status != trading.ItemStatusFilled {
			t.Fatalf("expected filled, got %s", item.Status)
		}
	}
}

func TestApplySessionStalenessExpiresSession(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	now := session.ExpiresAt.Add(time.Second)
	expired := trading.ApplySessionStaleness(session, []bonds.BondRecord{
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN = "RU000A1" }),
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN = "RU000A2" }),
	}, testutil.MakePortfolio(), trading.DefaultDeploySessionPolicy(), &now)
	if expired.Status != trading.DeploySessionExpired {
		t.Fatalf("expected expired, got %s", expired.Status)
	}
}

func TestApplySessionStalenessMarksItemStaleOnPriceDrift(t *testing.T) {
	session := makeSessionWithBuyItems("p1")
	p := testutil.MakePortfolio()
	last := 120.0
	bond := testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN = "RU000A1"; b.LastPrice = &last })
	policy := trading.DeploySessionPolicy{TTLHours: 24, PriceDriftStalePct: 5}
	updated := trading.ApplySessionStaleness(session, []bonds.BondRecord{
		bond,
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN = "RU000A2"; p := 100.0; b.LastPrice = &p }),
	}, p, policy, nil)
	if updated.Items[0].Status != trading.ItemStatusStale {
		t.Fatalf("expected stale, got %s", updated.Items[0].Status)
	}
}

func TestApplySessionStalenessMarksOverdueReinvestStale(t *testing.T) {
	now := time.Date(2026, 7, 25, 12, 0, 0, 0, time.UTC)
	due := time.Date(2026, 7, 24, 0, 0, 0, 0, time.UTC)
	price := 99.0
	session := trading.DeploySession{
		ID: "sess-reinvest", PortfolioID: "p1", Status: trading.DeploySessionActive,
		Items: []trading.DeploySessionItem{{
			ID: "item-reinvest", Kind: trading.DeploySessionItemReinvest, ISIN: "RU000NEW1",
			Name: "Replacement", Lots: 10, FIGI: bonds.StrPtr("FIGI-NEW"), SuggestedPricePct: price,
			EstimatedAmountRub: 100_000, Reason: "reinvest", DueDate: &due, Status: trading.ItemStatusPending,
		}},
		CashSnapshotRub: 0, CreatedAt: now.Add(-time.Hour), ExpiresAt: now.Add(23 * time.Hour),
	}
	last := 99.0
	updated := trading.ApplySessionStaleness(session, []bonds.BondRecord{
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN, b.FIGI = "RU000NEW1", "FIGI-NEW"; b.LastPrice = &last }),
	}, testutil.MakePortfolio(), trading.DefaultDeploySessionPolicy(), &now)
	if updated.Items[0].Status != trading.ItemStatusStale {
		t.Fatal("expected stale reinvest")
	}
	found := false
	for _, w := range updated.Warnings {
		if containsFold(w, "погашение источника") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected overdue warning, got %v", updated.Warnings)
	}
}

func TestApplySessionStalenessMarksPrematureReinvestStale(t *testing.T) {
	now := time.Date(2026, 7, 13, 12, 0, 0, 0, time.UTC)
	due := time.Date(2026, 7, 24, 0, 0, 0, 0, time.UTC)
	price := 99.0
	session := trading.DeploySession{
		ID: "sess-reinvest-early", PortfolioID: "p1", Status: trading.DeploySessionActive,
		Items: []trading.DeploySessionItem{{
			ID: "item-reinvest", Kind: trading.DeploySessionItemReinvest, ISIN: "RU000NEW1",
			Name: "Replacement", Lots: 10, SuggestedPricePct: price, EstimatedAmountRub: 100_000,
			Reason: "reinvest", DueDate: &due, Status: trading.ItemStatusPending,
		}},
		CashSnapshotRub: 0, CreatedAt: now.Add(-time.Hour), ExpiresAt: now.Add(23 * time.Hour),
	}
	last := 99.0
	updated := trading.ApplySessionStaleness(session, []bonds.BondRecord{
		testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN = "RU000NEW1"; b.LastPrice = &last }),
	}, testutil.MakePortfolio(), trading.DefaultDeploySessionPolicy(), &now)
	if updated.Items[0].Status != trading.ItemStatusStale {
		t.Fatal("expected premature reinvest stale")
	}
	found := false
	for _, w := range updated.Warnings {
		if contains(w, "доступна с") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected premature warning, got %v", updated.Warnings)
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || len(sub) == 0 || indexSub(s, sub))
}

func containsFold(s, sub string) bool {
	return contains(stringsToLower(s), stringsToLower(sub))
}

func indexSub(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

func stringsToLower(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + 32
		}
	}
	return string(b)
}

func TestStableIDDeterministic(t *testing.T) {
	id := trading.StableID("p1", "buy", "RU000A1")
	if len(id) != 32 {
		t.Fatalf("expected 32-char id, got %q", id)
	}
	if trading.StableID("p1", "buy", "RU000A1") != id {
		t.Fatal("stable id not deterministic")
	}
}
