package trading_test

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading/testutil"
)

func TestBuildHoldingsFromSnapshotAndUniverse(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000A1", "Hold Bond", "FIGI-HOLD"
		ytm := 17.5
		b.YTM = &ytm
	})
	snapshot := testutil.MakeAccountSnapshot(50_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = testutil.BondPosition("FIGI-HOLD", 2, 2)
	})
	holdings := trading.BuildHoldings(snapshot, []bonds.BondRecord{bond})
	if len(holdings) != 1 {
		t.Fatalf("expected 1 holding, got %d", len(holdings))
	}
	if holdings[0].ISIN != "RU000A1" || holdings[0].Lots != 2 {
		t.Fatalf("unexpected holding: %+v", holdings[0])
	}
	if holdings[0].YTM == nil || *holdings[0].YTM != 17.5 {
		t.Fatalf("expected ytm 17.5")
	}
	if holdings[0].MarketValueRub == nil || *holdings[0].MarketValueRub <= 0 {
		t.Fatalf("expected positive market value")
	}
}

func TestHoldingISINsFromSnapshotRequiresUniverseForFIGIMapping(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = "RU000A1", "FIGI-HOLD"
	})
	snapshot := testutil.MakeAccountSnapshot(50_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = testutil.BondPosition("FIGI-HOLD", 2, 2)
	})
	if len(trading.HoldingISINsFromSnapshot(snapshot, nil)) != 0 {
		t.Fatal("expected empty without universe")
	}
	isins := trading.HoldingISINsFromSnapshot(snapshot, []bonds.BondRecord{bond})
	if _, ok := isins["RU000A1"]; !ok {
		t.Fatalf("expected RU000A1 in %v", isins)
	}
}

func TestAdviseBuildsCashflowFromHoldings(t *testing.T) {
	today := time.Now()
	maturity := today.Add(180 * 24 * time.Hour)
	nextCoupon := today.Add(30 * 24 * time.Hour)
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000A2", "Cashflow Bond", "FIGI-CF"
		b.MaturityDate = &maturity
		rate := 12.0
		b.CouponRate = &rate
		period := 30
		b.CouponPeriodDays = &period
		b.NextCouponDate = &nextCoupon
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.HorizonDate = today.Add(365 * 24 * time.Hour)
		p.RiskProfile = portfolio.RiskProfileNormal
	})
	snapshot := testutil.MakeAccountSnapshot(10_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-CF"] = testutil.BondPosition("FIGI-CF", 1, 1)
	})
	advice := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bond}, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13, Today: &today,
	})
	if len(advice.Holdings) == 0 || len(advice.Cashflow) == 0 {
		t.Fatal("expected holdings and cashflow")
	}
	var coupons, maturities int
	for _, e := range advice.Cashflow {
		switch e.Kind {
		case "coupon":
			coupons++
		case "maturity":
			maturities++
		}
	}
	if coupons == 0 || maturities == 0 {
		t.Fatalf("expected coupon and maturity events, got coupons=%d maturities=%d", coupons, maturities)
	}
}

func TestAdviseSuggestsBuyWhenFreeCashAvailable(t *testing.T) {
	today := time.Now()
	var universe []bonds.BondRecord
	for i := 0; i < 8; i++ {
		maturity := today.Add(time.Duration(200+i) * 24 * time.Hour)
		price := 100.0
		ytm := 18.0 + float64(i)
		score := 80.0 + float64(i)
		api := false
		vol := 5_000_000.0
		idx := i
		universe = append(universe, testutil.MakeBond(func(b *bonds.BondRecord) {
			b.ISIN = fmt.Sprintf("RU000A%03d", idx)
			b.Name = fmt.Sprintf("Bond %d", idx)
			b.FIGI = fmt.Sprintf("FIGI-%d", idx)
			b.MaturityDate = &maturity
			b.LastPrice = &price
			b.YTM, b.Score = &ytm, &score
			b.YTMScore, b.RiskScore, b.LiquidityScore = &score, &score, &score
			b.APITradeAvailableFlag = &api
			b.VolumeRub = &vol
		}))
	}
	kind := trading.AccountKindSandbox
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.InitialAmountRub = 100_000
		p.HorizonDate = today.Add(400 * 24 * time.Hour)
		p.RiskProfile = portfolio.RiskProfileNormal
		p.AccountKind = &kind
		p.APITradeOnly = false
	})
	advice := trading.Advise(p, testutil.MakeAccountSnapshot(80_000), nil, nil, universe, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13, Today: &today,
	})
	var buys []trading.Suggestion
	seen := map[string]struct{}{}
	for _, s := range advice.Suggestions {
		if s.Kind == trading.SuggestionKindBuy {
			buys = append(buys, s)
			if _, ok := seen[s.ISIN]; ok {
				t.Fatalf("duplicate buy isin %s", s.ISIN)
			}
			seen[s.ISIN] = struct{}{}
		}
	}
	if len(buys) < portfolio.MinAutoPositions {
		t.Fatalf("expected >= %d buy suggestions, got %d", portfolio.MinAutoPositions, len(buys))
	}
	for _, s := range buys {
		if s.Lots < 1 || s.SuggestedPricePct == nil || s.MarketPricePct == nil {
			t.Fatalf("invalid buy suggestion: %+v", s)
		}
	}
}

func TestAdvisePutOfferReminderForNearOffer(t *testing.T) {
	today := time.Now()
	offerDate := today.Add(10 * 24 * time.Hour)
	start := today.Add(-5 * 24 * time.Hour)
	end := offerDate.Add(-24 * time.Hour)
	maturity := today.Add(500 * 24 * time.Hour)
	offerPrice := 100.0
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000PO", "Put Offer Bond", "FIGI-PO"
		b.MaturityDate = &maturity
		b.OfferDate = &offerDate
		b.OfferSubmissionStart = &start
		b.OfferSubmissionEnd = &end
		b.OfferPricePct = &offerPrice
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.HorizonDate = today.Add(600 * 24 * time.Hour)
	})
	snapshot := testutil.MakeAccountSnapshot(5_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-PO"] = testutil.BondPosition("FIGI-PO", 2, 2)
	})
	advice := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bond}, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13, Today: &today,
	})
	var reminders []trading.Suggestion
	for _, s := range advice.Suggestions {
		if s.Kind == trading.SuggestionKindPutOfferReminder {
			reminders = append(reminders, s)
		}
	}
	if len(reminders) != 1 {
		t.Fatalf("expected 1 reminder, got %d", len(reminders))
	}
	if reminders[0].ChatTemplate == nil || *reminders[0].ChatTemplate == "" {
		t.Fatal("expected chat template")
	}
	if reminders[0].Urgency != trading.SuggestionUrgencySoon && reminders[0].Urgency != trading.SuggestionUrgencyCritical {
		t.Fatalf("unexpected urgency %s", reminders[0].Urgency)
	}
}

func TestAdvisePutOfferWatchWhenWindowUnknown(t *testing.T) {
	today := time.Date(2026, 7, 10, 0, 0, 0, 0, time.UTC)
	offerDate := time.Date(2026, 8, 7, 0, 0, 0, 0, time.UTC)
	maturity := time.Date(2027, 7, 30, 0, 0, 0, 0, time.UTC)
	offerPrice := 100.0
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000A109874", "СамолетP15", "FIGI-SAM"
		b.MaturityDate = &maturity
		b.OfferDate = &offerDate
		b.OfferPricePct = &offerPrice
	})
	rate := 12.0
	period := 91
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.HorizonDate = time.Date(2028, 1, 1, 0, 0, 0, 0, time.UTC)
		p.Positions = []portfolio.PortfolioPosition{{
			ISIN: bond.ISIN, Secid: bond.ISIN, Name: bond.Name, Lots: 10, LotSize: 1,
			PurchaseCleanPricePct: 99, PurchaseDirtyPriceRub: 990, PurchaseACIRub: 0,
			PurchaseDate: time.Date(2026, 7, 8, 0, 0, 0, 0, time.UTC), PurchaseAmountRub: 99_000,
			CouponRate: &rate, FaceValue: 1000, MaturityDate: &maturity, OfferDate: &offerDate,
			OfferPricePct: &offerPrice, CouponPeriodDays: &period, Source: portfolio.PositionSourceAdopted,
			FIGI: bonds.StrPtr("FIGI-SAM"),
		}}
	})
	snapshot := testutil.MakeAccountSnapshot(5_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-SAM"] = testutil.BondPosition("FIGI-SAM", 10, 10)
	})
	advice := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bond}, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13, Today: &today,
	})
	var reminders, watches int
	for _, s := range advice.Suggestions {
		switch s.Kind {
		case trading.SuggestionKindPutOfferReminder:
			reminders++
		case trading.SuggestionKindPutOfferWatch:
			watches++
			if s.OfferWindowStatus == nil || *s.OfferWindowStatus != "unknown" {
				t.Fatalf("expected unknown window, got %v", s.OfferWindowStatus)
			}
			if !strings.Contains(s.Reason, "не объявлено") {
				t.Fatalf("expected awareness message, got %q", s.Reason)
			}
		}
	}
	if reminders != 0 || watches != 1 {
		t.Fatalf("reminders=%d watches=%d", reminders, watches)
	}
}

func TestAdviseIncludesPerformanceAndActiveOrders(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = "RU000P1", "FIGI-P1"
	})
	kind := trading.AccountKindSandbox
	started := time.Now().UTC().Format(time.RFC3339)
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.TradingStartedAt = &started
		p.AccountKind = &kind
	})
	snapshot := testutil.MakeAccountSnapshot(20_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-P1"] = testutil.BondPosition("FIGI-P1", 2, 2)
	})
	price := 96.0
	total := 1000.0
	comm := 1.0
	active := []trading.BrokerActiveOrder{{
		OrderID: "ord-1", RequestUID: "req-1", FIGI: "FIGI-P1", Direction: "BUY",
		LotsRequested: 1, Status: "EXECUTION_REPORT_STATUS_NEW",
		PricePct: &price, TotalOrderAmountRub: &total, InitialCommissionRub: &comm,
	}}
	advice := trading.Advise(p, snapshot, active, nil, []bonds.BondRecord{bond}, trading.AdviseParams{
		KeyRate: 16, TaxRate: 0.13,
	})
	if advice.Performance == nil || len(advice.ActiveOrders) != 1 {
		t.Fatal("expected performance and active orders")
	}
	if advice.AvailableMoneyRub != 20_000 {
		t.Fatalf("expected available 20000, got %v", advice.AvailableMoneyRub)
	}
}

func TestBuildHoldingsCashflowEmptyForNoPositions(t *testing.T) {
	today := time.Now()
	events := trading.BuildHoldingsCashflow(nil, today.Add(365*24*time.Hour), today)
	if len(events) != 0 {
		t.Fatalf("expected empty cashflow, got %d", len(events))
	}
}

func TestEffectiveTradingPositionsAdoptsBrokerHoldingsWithAveragePrice(t *testing.T) {
	today := time.Now()
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI, b.Name = "RU000A1", "FIGI-HOLD", "Hold Bond"
	})
	snapshot := testutil.MakeAccountSnapshot(50_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = testutil.BondPosition("FIGI-HOLD", 3, 3)
	})
	p := testutil.MakePortfolio()
	positions := trading.EffectiveTradingPositions(p, snapshot, []bonds.BondRecord{bond}, today)
	if len(positions) != 1 {
		t.Fatalf("expected 1 position, got %d", len(positions))
	}
	if positions[0].Source != portfolio.PositionSourceAdopted || positions[0].Lots != 3 {
		t.Fatalf("unexpected position: %+v", positions[0])
	}
	if positions[0].PurchaseCleanPricePct != 95 {
		t.Fatalf("expected avg price 95, got %v", positions[0].PurchaseCleanPricePct)
	}
}

func TestEffectiveTradingPositionsKeepsPendingPlanNotOnAccount(t *testing.T) {
	today := time.Now()
	bond := testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN, b.FIGI = "RU000ON", "FIGI-ON" })
	pendingBond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI, b.Name = "RU000PEND", "FIGI-PEND", "Pending"
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.Positions = []portfolio.PortfolioPosition{
			portfolio.PositionFromBond(pendingBond, 2, today, portfolio.PositionSourceInitial),
		}
	})
	snapshot := testutil.MakeAccountSnapshot(10_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-ON"] = testutil.BondPosition("FIGI-ON", 1, 1)
	})
	positions := trading.EffectiveTradingPositions(p, snapshot, []bonds.BondRecord{bond, pendingBond}, today)
	if len(positions) != 2 {
		t.Fatalf("expected 2 positions, got %d", len(positions))
	}
}

func TestValidateAttachSoftCountsDeployedBondsInEffectiveInitial(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) { b.ISIN, b.FIGI = "RU000A1", "FIGI-HOLD" })
	snapshot := testutil.MakeAccountSnapshot(20_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = testutil.BondPosition("FIGI-HOLD", 2, 2)
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.InitialAmountRub = 100_000 })
	v := trading.ValidateAttachSoft(snapshot, p, []bonds.BondRecord{bond})
	if v.EffectiveInitialAmountRub <= 20_000 {
		t.Fatalf("expected deployed value included, got %v", v.EffectiveInitialAmountRub)
	}
}

func TestValidateAttachSoftHandlesMissingPricePerLot(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.FIGI = "RU000A1", "FIGI-HOLD"
		b.LastPrice = nil
	})
	pos := testutil.BondPosition("FIGI-HOLD", 2, 2)
	pos.CurrentPricePct = nil
	pos.CurrentNKDRub = nil
	pos.AveragePricePct = nil
	snapshot := testutil.MakeAccountSnapshot(20_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = pos
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) { p.InitialAmountRub = 100_000 })
	v := trading.ValidateAttachSoft(snapshot, p, []bonds.BondRecord{bond})
	if !v.CanAttach || v.EffectiveInitialAmountRub != 20_000 {
		t.Fatalf("unexpected validation: %+v", v)
	}
}

func TestAdviseEmitsRiskSellOnDefaultEscalation(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000A1", "Risk Bond", "FIGI-HOLD"
		ytm := 17.5
		b.YTM = &ytm
		b.HasDefault = true
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.HorizonDate = time.Now().Add(365 * 24 * time.Hour)
		p.RiskProfile = portfolio.RiskProfileNormal
		p.RiskBaselines["RU000A1"] = portfolio.RiskSnapshot{CreditRating: bond.CreditRating}
	})
	snapshot := testutil.MakeAccountSnapshot(10_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = testutil.BondPosition("FIGI-HOLD", 2, 2)
	})
	advice := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bond}, trading.AdviseParams{
		KeyRate: 14.5, TaxRate: 0.13,
	})
	var sells []trading.Suggestion
	for _, s := range advice.Suggestions {
		if s.Kind == trading.SuggestionKindSell {
			sells = append(sells, s)
		}
	}
	if len(sells) != 1 || sells[0].ISIN != "RU000A1" || !sells[0].RiskAcknowledgeable {
		t.Fatalf("unexpected sells: %+v", sells)
	}
	if sells[0].Urgency != trading.SuggestionUrgencyCritical {
		t.Fatalf("expected critical urgency")
	}
}

func TestAdviseSkipsRiskSellWhenBaselineMatchesCurrent(t *testing.T) {
	bond := testutil.MakeBond(func(b *bonds.BondRecord) {
		b.ISIN, b.Name, b.FIGI = "RU000A1", "Risk Bond", "FIGI-HOLD"
		b.HasDefault = true
	})
	p := testutil.MakePortfolio(func(p *portfolio.Portfolio) {
		p.HorizonDate = time.Now().Add(365 * 24 * time.Hour)
		p.RiskBaselines["RU000A1"] = portfolio.RiskSnapshot{HasDefault: true, CreditRating: bond.CreditRating}
	})
	snapshot := testutil.MakeAccountSnapshot(10_000, func(s *trading.BrokerSnapshot) {
		s.BondPositions["FIGI-HOLD"] = testutil.BondPosition("FIGI-HOLD", 2, 2)
	})
	advice := trading.Advise(p, snapshot, nil, nil, []bonds.BondRecord{bond}, trading.AdviseParams{
		KeyRate: 14.5, TaxRate: 0.13,
	})
	for _, s := range advice.Suggestions {
		if s.Kind == trading.SuggestionKindSell {
			t.Fatal("expected no sell suggestions")
		}
	}
}
