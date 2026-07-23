package tinvest

import (
	"testing"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
	pb "github.com/russianinvestments/invest-api-go-sdk/proto"
)

func TestMapCouponType(t *testing.T) {
	cases := []struct {
		raw  int32
		want bonds.CouponType
	}{
		{int32(pb.CouponType_COUPON_TYPE_CONSTANT), bonds.CouponTypeFixed},
		{int32(pb.CouponType_COUPON_TYPE_FIX), bonds.CouponTypeFixed},
		{int32(pb.CouponType_COUPON_TYPE_FLOATING), bonds.CouponTypeFloating},
		{int32(pb.CouponType_COUPON_TYPE_VARIABLE), bonds.CouponTypeVariable},
		{int32(pb.CouponType_COUPON_TYPE_OTHER), bonds.CouponTypeVariable},
		{0, bonds.CouponTypeUnknown},
	}
	for _, tc := range cases {
		if got := mapCouponType(tc.raw); got != tc.want {
			t.Fatalf("mapCouponType(%d) = %q, want %q", tc.raw, got, tc.want)
		}
	}
}

func TestApplyTInvestData_SetsFIGIAndFlags(t *testing.T) {
	callDate := "2027-01-15"
	bond := bonds.BondRecord{ISIN: "RU000A10B8D9", Name: "Test"}
	applyTInvestData(&bond, tinvestBondData{
		FIGI:                  "BBGTEST",
		FloatingCouponFlag:    true,
		AmortizationFlag:      true,
		SubordinatedFlag:      true,
		ForQualInvestorFlag:   true,
		LiquidityFlag:         true,
		APITradeAvailableFlag: true,
		CallDate:              &callDate,
		RiskLevel:             int(bonds.RiskLevelModerate),
		InstrumentFullName:      "Full name",
		Sector:                "financial",
		AssetUID:              "asset-1",
	})
	if bond.FIGI != "BBGTEST" {
		t.Fatalf("FIGI = %q", bond.FIGI)
	}
	if !bond.TInvestEnriched {
		t.Fatal("expected tinvest_enriched=true")
	}
	if bond.CouponType != bonds.CouponTypeFloating {
		t.Fatalf("coupon type = %q", bond.CouponType)
	}
	if bond.RiskLevel != bonds.RiskLevelModerate {
		t.Fatalf("risk level = %v", bond.RiskLevel)
	}
	if bond.APITradeAvailableFlag == nil || !*bond.APITradeAvailableFlag {
		t.Fatal("expected api_trade_available=true")
	}
}

func TestResolveCouponTypeFromSchedule(t *testing.T) {
	payments := []bonds.CouponPayment{
		{CouponTypeRaw: int(pb.CouponType_COUPON_TYPE_FLOATING)},
		{CouponTypeRaw: int(pb.CouponType_COUPON_TYPE_FLOATING)},
		{CouponTypeRaw: int(pb.CouponType_COUPON_TYPE_VARIABLE)},
	}
	if got := resolveCouponTypeFromSchedule(payments); got != bonds.CouponTypeFloating {
		t.Fatalf("got %q, want floating", got)
	}
}
