package testutil

import (
	"time"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	"github.com/tonatos/instrumenta/backend/internal/domain/portfolio"
	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
	"github.com/tonatos/instrumenta/backend/internal/domain/trading"
)

func MakeBond(opts ...func(*bonds.BondRecord)) bonds.BondRecord {
	maturity := time.Date(2027, 6, 1, 0, 0, 0, 0, time.UTC)
	price := 99.0
	ytm := 18.0
	score := 80.0
	api := true
	b := bonds.BondRecord{
		Secid: "RU000A", ISIN: "RU000ATEST", Name: "Test Bond",
		MaturityDate: &maturity, EffectiveDate: &maturity,
		DaysToMaturity: bonds.IntPtr(365),
		LastPrice: &price, YTM: &ytm, Score: &score,
		YTMScore: &score, RiskScore: &score, LiquidityScore: &score,
		RiskLevel: bonds.RiskLevelLow, CreditRating: bonds.StrPtr("ruA"),
		LotSize: 1, FaceValue: 1000, VolumeRub: bonds.FloatPtr(1_000_000),
		APITradeAvailableFlag: &api,
	}
	for _, opt := range opts {
		opt(&b)
	}
	return b
}

func MakePortfolio(opts ...func(*portfolio.Portfolio)) portfolio.Portfolio {
	p := portfolio.Portfolio{
		ID: "test-portfolio", Name: "Test Portfolio",
		InitialAmountRub: 100_000, HorizonDate: time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC),
		RiskProfile: portfolio.RiskProfileNormal, RiskBaselines: make(map[string]portfolio.RiskSnapshot),
	}
	for _, opt := range opts {
		opt(&p)
	}
	return p
}

func MakeAccountSnapshot(money float64, opts ...func(*trading.BrokerSnapshot)) trading.BrokerSnapshot {
	s := trading.BrokerSnapshot{
		AccountID: "acc-clean", AccountKind: trading.AccountKindSandbox,
		MoneyRub: shared.Rub(money), BondPositions: map[string]trading.BrokerBondPosition{},
		FetchedAt: time.Now().UTC().Format(time.RFC3339),
	}
	for _, opt := range opts {
		opt(&s)
	}
	return s
}

func BondPosition(figi string, lots, quantity int) trading.BrokerBondPosition {
	price := shared.PriceUnitPct(96.0)
	nkd := shared.Rub(5.0)
	avg := shared.PriceUnitPct(95.0)
	return trading.BrokerBondPosition{
		FIGI: figi, InstrumentUID: "uid-hold", Ticker: "SU26238",
		Quantity: quantity, Lots: lots, CurrentPricePct: &price, CurrentNKDRub: &nkd,
		AveragePricePct: &avg,
	}
}
