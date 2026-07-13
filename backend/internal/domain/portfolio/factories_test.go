package portfolio_test

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/portfolio"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

func makeBond(
	isin, name string,
	maturity time.Time,
	price, ytm, score float64,
	apiTrade *bool,
	overrides func(*bonds.BondRecord),
) bonds.BondRecord {
	dtm := int(maturity.Sub(shared.DateOnly(time.Now())).Hours() / 24)
	if dtm < 1 {
		dtm = 1
	}
	ytmNet := ytm * 0.87
	b := bonds.BondRecord{
		Secid: isin[:min(6, len(isin))], ISIN: isin, Name: name,
		MaturityDate: &maturity, EffectiveDate: &maturity, DaysToMaturity: &dtm,
		LastPrice: &price, YTM: &ytm, YTMNet: &ytmNet, Score: &score,
		YTMScore: &score, RiskScore: &score, LiquidityScore: &score,
		RiskLevel: bonds.RiskLevelLow, CreditRating: bonds.StrPtr("ruA"),
		LotSize: 1, FaceValue: 1000, VolumeRub: bonds.FloatPtr(1_000_000),
		APITradeAvailableFlag: apiTrade,
	}
	if overrides != nil {
		overrides(&b)
	}
	dirty := price/100*1000 + deref(b.AccruedInterest)
	bondDirty := dirty
	_ = bondDirty
	return b
}

func makeLiveBond(isin, name string, maturity time.Time, price, aci float64, couponRate *float64, couponPeriod int, nextCoupon *time.Time, ytm, score float64) bonds.BondRecord {
	api := true
	b := makeBond(isin, name, maturity, price, ytm, score, &api, func(br *bonds.BondRecord) {
		br.AccruedInterest = &aci
		br.CouponRate = couponRate
		br.CouponPeriodDays = &couponPeriod
		br.NextCouponDate = nextCoupon
	})
	return b
}

func deref(f *float64) float64 {
	if f == nil {
		return 0
	}
	return *f
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func aa19dfdPortfolio() portfolio.Portfolio {
	today := shared.MustParseDate("2026-07-07")
	return portfolio.Portfolio{
		ID: "aa19dfd359c5489988adac94df8bfe8b", Name: "Первый Боевой",
		InitialAmountRub: 20_000, HorizonDate: shared.MustParseDate("2027-01-01"),
		RiskProfile: portfolio.RiskProfileAggressive, CashBalanceRub: 2_982.08,
		APITradeOnly: true,
		Positions: []portfolio.PortfolioPosition{
			pos("RU000A100PB0", "ЖКХРСЯ БО1", 5, 99.5, 1039.74, 44.74, today, 5198.7, 23, shared.MustParseDate("2026-07-28"), 91, shared.MustParseDate("2026-07-28")),
			pos("RU000A109TG2", "iКарРус1P4", 6, 96.8, 981.36, 13.36, today, 5888.16, 0, shared.MustParseDate("2026-10-08"), 30, shared.MustParseDate("2026-07-10")),
			pos("RU000A109908", "МВ ФИН 1P5", 6, 98.8, 988.51, 0.51, today, 5931.06, 0, shared.MustParseDate("2026-08-06"), 30, shared.MustParseDate("2026-08-06")),
		},
	}
}

func pos(isin, name string, lots int, clean, dirty, aci float64, purchase time.Time, amount float64, coupon float64, maturity time.Time, period int, nextCoupon time.Time) portfolio.PortfolioPosition {
	var couponRate *float64
	if coupon > 0 {
		couponRate = &coupon
	}
	periodDays := period
	return portfolio.PortfolioPosition{
		ISIN: isin, Secid: isin, Name: name, Lots: lots, LotSize: 1,
		PurchaseCleanPricePct: clean, PurchaseDirtyPriceRub: dirty, PurchaseACIRub: aci,
		PurchaseDate: purchase, PurchaseAmountRub: amount, CouponRate: couponRate,
		FaceValue: 1000, MaturityDate: &maturity, CouponPeriodDays: &periodDays,
		NextCouponDate: &nextCoupon, Source: portfolio.PositionSourceInitial,
	}
}

func aa19dfdUniverse() []bonds.BondRecord {
	return []bonds.BondRecord{
		makeLiveBond("RU000A100PB0", "ЖКХРСЯ БО1", shared.MustParseDate("2026-07-28"), 99.5, 44.74, bonds.FloatPtr(23), 91, ptr(shared.MustParseDate("2026-07-28")), 20, 85),
		makeLiveBond("RU000A109TG2", "iКарРус1P4", shared.MustParseDate("2026-10-08"), 96.8, 13.36, nil, 30, ptr(shared.MustParseDate("2026-07-10")), 24, 95),
		makeLiveBond("RU000A109908", "МВ ФИН 1P5", shared.MustParseDate("2026-08-06"), 98.8, 0.51, nil, 30, ptr(shared.MustParseDate("2026-08-06")), 20, 85),
		makeLiveBond("RU000A107BH2", "ИЛСБО-1-1Р", shared.MustParseDate("2026-11-19"), 94.5, 5, nil, 30, nil, 18, 82),
		makeLiveBond("RU000A1074E7", "РУССОЙЛ-01", shared.MustParseDate("2026-10-20"), 99.8, 1, nil, 30, nil, 19, 88),
		makeLiveBond("RU000A107G22", "КОРПСАН 01", shared.MustParseDate("2026-12-18"), 95, 3, nil, 30, nil, 21, 87),
		makeLiveBond("RU000A107KR2", "МигКр 04", shared.MustParseDate("2026-12-31"), 96, 2, nil, 30, nil, 20, 86),
	}
}

func aa19dfdLivePortfolio() portfolio.Portfolio {
	liveToday := shared.MustParseDate("2026-07-08")
	p := aa19dfdPortfolio()
	p.Mode = portfolio.PortfolioModeTrading
	p.CashBalanceRub = 632.14
	p.Positions = []portfolio.PortfolioPosition{
		pos("RU000A100PB0", "ЖКХРСЯ БО1", 5, 99.5, 1039.74, 44.74, shared.MustParseDate("2026-07-07"), 5198.7, 23, shared.MustParseDate("2026-07-28"), 91, shared.MustParseDate("2026-07-28")),
		pos("RU000A109908", "МВ ФИН 1P5", 26, 98.79, 988.41, 0.51, shared.MustParseDate("2026-07-07"), 5930.46, 0, shared.MustParseDate("2026-08-06"), 30, shared.MustParseDate("2026-08-06")),
		pos("RU000A106UB7", "Кириллица3", 34, 98.37, 990.48, 6.78, liveToday, 33676.32, 16.5, shared.MustParseDate("2026-08-22"), 30, shared.MustParseDate("2026-07-23")),
		pos("RU000A107G22", "КОРПСАН 01", 37, 90.68, 914.61, 7.81, liveToday, 33840.57, 15, shared.MustParseDate("2026-12-18"), 91, shared.MustParseDate("2026-09-18")),
		pos("RU000A103WB0", "СлавЭКО1Р1", 34, 94.9, 974.62, 25.62, liveToday, 33137.08, 11, shared.MustParseDate("2026-10-13"), 91, shared.MustParseDate("2026-07-14")),
		posAdopted("RU000A109TG2", "iКарРус1P4", 40, 96.89, 982.26, 13.36, liveToday, 35361.36, 0, shared.MustParseDate("2026-10-08"), 30, shared.MustParseDate("2026-07-10")),
		posAdopted("RU000A106YN4", "ГрупПро1P3", 33, 98.14, 991.92, 10.52, liveToday, 48604.08, 16, shared.MustParseDate("2026-09-12"), 30, shared.MustParseDate("2026-07-14")),
		posAdopted("RU000A106VN0", "ТРДБ Б0-01", 42, 99.1, 996.42, 5.42, liveToday, 41849.64, 18, shared.MustParseDate("2026-08-27"), 30, shared.MustParseDate("2026-07-28")),
	}
	return p
}

func posAdopted(isin, name string, lots int, clean, dirty, aci float64, purchase time.Time, amount float64, coupon float64, maturity time.Time, period int, nextCoupon time.Time) portfolio.PortfolioPosition {
	p := pos(isin, name, lots, clean, dirty, aci, purchase, amount, coupon, maturity, period, nextCoupon)
	p.Source = portfolio.PositionSourceAdopted
	return p
}

func aa19dfdLiveUniverse() []bonds.BondRecord {
	base := make(map[string]bonds.BondRecord)
	for _, b := range aa19dfdUniverse() {
		base[b.ISIN] = b
	}
	extras := []struct {
		isin, name string
		maturity time.Time
		price, aci, coupon float64
		next                 time.Time
	}{
		{"RU000A106UB7", "Кириллица3", shared.MustParseDate("2026-08-22"), 98.37, 6.78, 16.5, shared.MustParseDate("2026-07-23")},
		{"RU000A103WB0", "СлавЭКО1Р1", shared.MustParseDate("2026-10-13"), 94.9, 25.62, 11, shared.MustParseDate("2026-07-14")},
		{"RU000A106YN4", "ГрупПро1P3", shared.MustParseDate("2026-09-12"), 98.14, 10.52, 16, shared.MustParseDate("2026-07-14")},
		{"RU000A106VN0", "ТРДБ Б0-01", shared.MustParseDate("2026-08-27"), 99.1, 5.42, 18, shared.MustParseDate("2026-07-28")},
		{"RU000A108A01", "НовТех1Р2", shared.MustParseDate("2027-03-01"), 95, 2, 22, shared.MustParseDate("2026-10-01")},
		{"RU000A108A08", "АйДиКоле06", shared.MustParseDate("2026-11-21"), 99, 1, 16, shared.MustParseDate("2026-10-01")},
	}
	for _, e := range extras {
		if _, ok := base[e.isin]; !ok {
			base[e.isin] = makeLiveBond(e.isin, e.name, e.maturity, e.price, e.aci, bonds.FloatPtr(e.coupon), 30, ptr(e.next), 20, 90)
		}
	}
	base["RU000A107G22"] = makeLiveBond("RU000A107G22", "КОРПСАН 01", shared.MustParseDate("2026-12-18"), 90.68, 7.81, bonds.FloatPtr(15), 91, ptr(shared.MustParseDate("2026-09-18")), 21, 87)
	base["RU000A109TG2"] = makeLiveBond("RU000A109TG2", "iКарРус1P4", shared.MustParseDate("2026-10-08"), 96.89, 13.36, nil, 30, ptr(shared.MustParseDate("2026-07-10")), 24, 95)
	out := make([]bonds.BondRecord, 0, len(base))
	for _, b := range base {
		out = append(out, b)
	}
	return out
}

func ptr(t time.Time) *time.Time { return &t }
