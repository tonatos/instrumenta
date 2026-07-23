package shared_test

import (
	"math"
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/domain/shared"
)

func approxEqual(t *testing.T, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-9 {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestBondCleanPricePctFromRub(t *testing.T) {
	pct := shared.BondCleanPricePctFromRub(1009.9245, 1000.0)
	approxEqual(t, float64(pct), 100.99245)
}

func TestBondCleanPriceQuotationConvertsPctToRub(t *testing.T) {
	q := shared.BondCleanPriceQuotation(100.4095, 1000.0)
	if q.Units != 1004 || q.Nano != 95_000_000 {
		t.Fatalf("got units=%d nano=%d, want units=1004 nano=95000000", q.Units, q.Nano)
	}
}

func TestPctToQuotationRoundtrip(t *testing.T) {
	original := shared.PriceUnitPct(100.5)
	q := shared.PctToQuotation(original)
	if q.Units != 100 || q.Nano != 500_000_000 {
		t.Fatalf("got units=%d nano=%d", q.Units, q.Nano)
	}
	approxEqual(t, float64(shared.QuotationToPct(q)), 100.5)
}

func TestPctToQuotationLowPrecision(t *testing.T) {
	q := shared.PctToQuotation(99.001)
	if q.Units != 99 || q.Nano != 1_000_000 {
		t.Fatalf("got units=%d nano=%d", q.Units, q.Nano)
	}
	approxEqual(t, float64(shared.QuotationToPct(q)), 99.001)
}

func TestPctToQuotationNegativeUnsupported(t *testing.T) {
	q := shared.PctToQuotation(0.5)
	if q.Units != 0 || q.Nano != 500_000_000 {
		t.Fatalf("got units=%d nano=%d", q.Units, q.Nano)
	}
}

func TestLotCostRubBasic(t *testing.T) {
	cost := shared.LotCostRub(100.0, 1000.0, 10, 0.0)
	approxEqual(t, float64(cost), 10_000.0)
}

func TestLotCostRubWithNKD(t *testing.T) {
	cost := shared.LotCostRub(100.0, 1000.0, 10, 5.0)
	approxEqual(t, float64(cost), 10_050.0)
}

func TestLotCostRubDiscount(t *testing.T) {
	cost := shared.LotCostRub(99.5, 1000.0, 10, 0.0)
	approxEqual(t, float64(cost), 9_950.0)
}

func TestOrderAmountRubMultipliesLots(t *testing.T) {
	total := shared.OrderAmountRub(100.0, 1000.0, 10, 5, 0.0)
	approxEqual(t, float64(total), 50_000.0)
}

type fakeMoneyValue struct {
	currency string
	units    int64
	nano     int64
}

func (f fakeMoneyValue) Currency() string { return f.currency }
func (f fakeMoneyValue) Units() int64     { return f.units }
func (f fakeMoneyValue) Nano() int64      { return f.nano }

func TestMoneyValueToRubRubCurrency(t *testing.T) {
	result := shared.MoneyValueToRub(fakeMoneyValue{
		currency: "rub",
		units:    1000,
		nano:     500_000_000,
	})
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	approxEqual(t, float64(*result), 1000.5)
}

func TestMoneyValueToRubForeignCurrencyNone(t *testing.T) {
	result := shared.MoneyValueToRub(fakeMoneyValue{
		currency: "usd",
		units:    100,
		nano:     0,
	})
	if result != nil {
		t.Fatalf("expected nil, got %v", *result)
	}
}

func TestMoneyValueToRubNoneInput(t *testing.T) {
	if shared.MoneyValueToRub(nil) != nil {
		t.Fatal("expected nil for nil input")
	}
}

type fakeQuotation struct {
	units int64
	nano  int64
}

func (f fakeQuotation) Units() int64 { return f.units }
func (f fakeQuotation) Nano() int64  { return f.nano }

func TestQuotationToFloatZeroReturnsNone(t *testing.T) {
	if shared.QuotationToFloat(fakeQuotation{units: 0, nano: 0}) != nil {
		t.Fatal("expected nil for zero quotation")
	}
}

func TestQuotationToFloatPositiveFractional(t *testing.T) {
	result := shared.QuotationToFloat(fakeQuotation{units: 100, nano: 500_000_000})
	if result == nil {
		t.Fatal("expected non-nil result")
	}
	approxEqual(t, *result, 100.5)
}

func TestRubTypeIsFloat64(t *testing.T) {
	var value shared.Rub = 1000.0
	approxEqual(t, float64(value)+1.0, 1001.0)
}
