package screening_test

import (
	"math"
	"testing"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/screening"
)

func ptr[T any](v T) *T { return &v }

func approxEqual(t *testing.T, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-9 {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestCalcYTMScoreHigherForBetterYTM(t *testing.T) {
	low := screening.CalcYTMScore(ptr(10.0), 12.0, 8.0)
	high := screening.CalcYTMScore(ptr(18.0), 12.0, 8.0)
	if high <= low {
		t.Fatalf("expected high > low, got high=%v low=%v", high, low)
	}
}

func TestScoreBondsAllProfilesFillsYTMNetAndProfileScores(t *testing.T) {
	maturity := time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC)
	bondList := []bonds.BondRecord{{
		Secid:        "TEST",
		ISIN:         "RU000TEST",
		Name:         "Test",
		YTM:          ptr(16.0),
		RiskLevel:    bonds.RiskLevelLow,
		VolumeRub:    ptr(1_000_000.0),
		MaturityDate: &maturity,
	}}
	scored := screening.ScoreBondsAllProfiles(bondList, 14.5, 0.13)
	bond := scored[0]
	if bond.YTMNet == nil || bond.Score == nil {
		t.Fatal("expected ytm_net and score to be set")
	}
	if len(bond.ProfileScores) != 3 {
		t.Fatalf("expected 3 profile scores, got %v", bond.ProfileScores)
	}
	for _, key := range []string{"conservative", "normal", "aggressive"} {
		if _, ok := bond.ProfileScores[key]; !ok {
			t.Fatalf("missing profile score %q", key)
		}
	}
	approxEqual(t, *bond.Score, bond.ProfileScores["normal"])
}

func TestConservativeScoreLowerThanNormalForHighYTMModerateRisk(t *testing.T) {
	bond := makeBond("VDO", 28.0, ptr("ruBBB"), bonds.RiskLevelModerate, 5_000_000)
	scored := screening.ScoreBondsAllProfiles([]bonds.BondRecord{bond}, 14.5, 0.13)
	profileScores := scored[0].ProfileScores
	if profileScores["conservative"] >= profileScores["normal"] {
		t.Fatalf("expected conservative < normal, got %v vs %v",
			profileScores["conservative"], profileScores["normal"])
	}
}

func TestDurationAdjustmentAppliesToAllProfileScores(t *testing.T) {
	bond := makeBond("LONG", 22.0, ptr("ruA"), bonds.RiskLevelLow, 5_000_000)
	bond.DurationDays = ptr(730.0)
	scored := screening.ScoreBondsAllProfiles([]bonds.BondRecord{bond}, 14.5, 0.13)
	before := scored[0].ProfileScores
	policy := screening.DurationPolicy{
		RateScenario:        screening.RateScenarioCut,
		DurationScoreWeight: 0.20,
	}
	adjusted := screening.ApplyDurationScoring(scored, policy, screening.RiskProfileNormal)
	after := adjusted[0].ProfileScores
	durationScale := screening.DurationScaleYears(scored, policy)
	adjustment := screening.DurationAdjustmentForBond(&scored[0], policy, durationScale)
	if adjustment <= 0 {
		t.Fatalf("expected positive adjustment, got %v", adjustment)
	}
	for key, beforeScore := range before {
		want := math.Min(100.0, beforeScore+adjustment)
		approxEqual(t, after[key], want)
	}
}

func makeBond(
	secid string,
	ytm float64,
	creditRating *string,
	riskLevel bonds.RiskLevel,
	prevVolumeRub float64,
) bonds.BondRecord {
	maturity := time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC)
	return bonds.BondRecord{
		Secid:         secid,
		ISIN:          "RU000" + secid,
		Name:          secid,
		YTM:           &ytm,
		CreditRating:  creditRating,
		RiskLevel:     riskLevel,
		PrevVolumeRub: &prevVolumeRub,
		MaturityDate:  &maturity,
		CouponType:    bonds.CouponTypeFixed,
	}
}

func TestUnratedRanksBelowEqualYTMRatedBond(t *testing.T) {
	bondList := []bonds.BondRecord{
		makeBond("UNRATED", 30.0, nil, bonds.RiskLevelHigh, 5_000_000),
		makeBond("RATED", 30.0, ptr("ruBB"), bonds.RiskLevelHigh, 5_000_000),
	}
	scored := screening.ScoreBondsForProfile(
		bondList,
		screening.RiskProfileAggressive,
		14.5, 0.13,
		screening.DefaultDurationPolicy,
	)
	bySecid := map[string]bonds.BondRecord{}
	for _, b := range scored {
		bySecid[b.Secid] = b
	}
	if bySecid["RATED"].Score == nil || bySecid["UNRATED"].Score == nil {
		t.Fatal("expected scores to be set")
	}
	if *bySecid["RATED"].Score <= *bySecid["UNRATED"].Score {
		t.Fatalf("expected RATED > UNRATED")
	}
	if scored[0].Secid != "RATED" {
		t.Fatalf("expected RATED first, got %s", scored[0].Secid)
	}
}

func TestDistressYTMLosesToModerateBond(t *testing.T) {
	bondList := []bonds.BondRecord{
		makeBond("DISTRESS", 60.0, ptr("ruBB"), bonds.RiskLevelHigh, 5_000_000),
		makeBond("HEALTHY", 25.0, ptr("ruBB"), bonds.RiskLevelHigh, 5_000_000),
	}
	scored := screening.ScoreBondsForProfile(
		bondList,
		screening.RiskProfileAggressive,
		14.5, 0.13,
		screening.DefaultDurationPolicy,
	)
	bySecid := map[string]bonds.BondRecord{}
	for _, b := range scored {
		bySecid[b.Secid] = b
	}
	if *bySecid["HEALTHY"].Score <= *bySecid["DISTRESS"].Score {
		t.Fatal("expected HEALTHY > DISTRESS")
	}
	if scored[0].Secid != "HEALTHY" {
		t.Fatalf("expected HEALTHY first, got %s", scored[0].Secid)
	}
}

func TestAggressivePrefersVDOOverLowYieldIG(t *testing.T) {
	bondList := []bonds.BondRecord{
		makeBond("VDO", 35.0, ptr("ruBBB-"), bonds.RiskLevelModerate, 5_000_000),
		makeBond("IG", 20.65, ptr("ruAA-"), bonds.RiskLevelLow, 50_000_000),
	}
	scored := screening.ScoreBondsForProfile(
		bondList,
		screening.RiskProfileAggressive,
		14.5, 0.13,
		screening.DefaultDurationPolicy,
	)
	bySecid := map[string]bonds.BondRecord{}
	for _, b := range scored {
		bySecid[b.Secid] = b
	}
	if *bySecid["VDO"].Score <= *bySecid["IG"].Score {
		t.Fatal("expected VDO > IG")
	}
	if scored[0].Secid != "VDO" {
		t.Fatalf("expected VDO first, got %s", scored[0].Secid)
	}
}

func TestFloatingCouponHasNoExtraRiskPenalty(t *testing.T) {
	fixed := makeBond("FIXED", 30.0, ptr("ruBBB-"), bonds.RiskLevelHigh, 5_000_000)
	floating := makeBond("FLOAT", 30.0, ptr("ruBBB-"), bonds.RiskLevelHigh, 5_000_000)
	floating.CouponType = bonds.CouponTypeFloating
	floating.FloatingCouponFlag = true

	riskFreeNet := 14.5 * (1 - 0.13)
	fixedYTMNet := 30.0 * 0.87
	floatingYTMNet := 30.0 * 0.87
	if screening.CalcRiskScore(&fixed) != screening.CalcRiskScore(&floating) {
		t.Fatal("floating coupon must not change risk score")
	}
	if screening.CalcDistressPenalty(&fixed, &fixedYTMNet, riskFreeNet) !=
		screening.CalcDistressPenalty(&floating, &floatingYTMNet, riskFreeNet) {
		t.Fatal("floating coupon must not change distress penalty")
	}
}

func TestExtremeYTMKeepsNonzeroYTMScore(t *testing.T) {
	riskFreeNet := 14.5 * (1 - 0.13)
	ytmNet := 69.39 * (1 - 0.13)
	score := screening.CalcYTMScore(&ytmNet, riskFreeNet, 40.0)
	if score <= 0.0 {
		t.Fatalf("expected positive ytm score, got %v", score)
	}
}

func TestThinVolumeGetsLowLiquidityScore(t *testing.T) {
	score := screening.CalcLiquidityScore(ptr(212_077.0))
	if score >= 20.0 {
		t.Fatalf("expected score < 20, got %v", score)
	}
}

func TestLiquidityScoreUsesAbsoluteAnchors(t *testing.T) {
	floorScore := screening.CalcLiquidityScore(ptr(500_000.0))
	goodScore := screening.CalcLiquidityScore(ptr(10_000_000.0))
	midScore := screening.CalcLiquidityScore(ptr(2_000_000.0))

	approxEqual(t, floorScore, 0.0)
	approxEqual(t, goodScore, 100.0)
	if midScore <= 40.0 || midScore >= 55.0 {
		t.Fatalf("expected mid score in (40, 55), got %v", midScore)
	}
	approxEqual(t, screening.CalcLiquidityScore(ptr(2_000_000.0)), midScore)
}

func TestCalcDistressPenaltyZeroBelowThreshold(t *testing.T) {
	riskFreeNet := 14.5 * (1 - 0.13)
	bond := makeBond("X", 20.0, ptr("ruBB"), bonds.RiskLevelHigh, 5_000_000)
	spread := riskFreeNet + 10.0
	if screening.CalcDistressPenalty(&bond, &spread, riskFreeNet) != 0.0 {
		t.Fatal("expected zero distress penalty below threshold")
	}
}

func TestCalcDistressPenaltyIGHasHigherThreshold(t *testing.T) {
	riskFreeNet := 14.5 * (1 - 0.13)
	ig := makeBond("IG", 35.0, ptr("ruBBB-"), bonds.RiskLevelHigh, 5_000_000)
	junk := makeBond("JUNK", 35.0, ptr("ruBB"), bonds.RiskLevelHigh, 5_000_000)
	spread := riskFreeNet + 32.0
	if screening.CalcDistressPenalty(&ig, &spread, riskFreeNet) != 0.0 {
		t.Fatal("expected zero IG distress penalty")
	}
	if screening.CalcDistressPenalty(&junk, &spread, riskFreeNet) <= 0.0 {
		t.Fatal("expected positive junk distress penalty")
	}
}

func TestScoringYTMNetCapsPhantomYieldToCall(t *testing.T) {
	callDate := time.Date(2026, 10, 6, 0, 0, 0, 0, time.UTC)
	maturity := time.Date(2027, 9, 30, 0, 0, 0, 0, time.UTC)
	ytmNet := 68.66 * 0.87
	bond := bonds.BondRecord{
		Secid:        "CALL",
		ISIN:         "RU000CALL",
		Name:         "CALL",
		YTM:          ptr(68.66),
		YTMNet:       &ytmNet,
		CouponRate:   ptr(24.0),
		CallDate:     &callDate,
		MaturityDate: &maturity,
		RiskLevel:    bonds.RiskLevelHigh,
		CreditRating: ptr("ruB+"),
	}
	riskFreeNet := 14.5 * 0.87
	scoring := screening.ScoringYTMNet(&bond, riskFreeNet, 0.87)
	if scoring == nil {
		t.Fatal("expected scoring ytm net")
	}
	approxEqual(t, *scoring, 24.0*0.87)
	if *scoring >= ytmNet {
		t.Fatal("expected scoring ytm net < bond ytm net")
	}
}

func TestCallableBondRanksBelowEquivalentNonCall(t *testing.T) {
	maturity := time.Date(2027, 9, 30, 0, 0, 0, 0, time.UTC)
	vol := 876_592.0
	plain := bonds.BondRecord{
		Secid: "PLAIN", ISIN: "RU000PLAIN", Name: "PLAIN",
		YTM: ptr(28.0), CouponRate: ptr(24.0), CreditRating: ptr("ruBBB-"),
		RiskLevel: bonds.RiskLevelModerate, PrevVolumeRub: &vol, MaturityDate: &maturity,
	}
	callDate := time.Date(2026, 10, 6, 0, 0, 0, 0, time.UTC)
	callable := bonds.BondRecord{
		Secid: "CALL", ISIN: "RU000CALL", Name: "CALL",
		YTM: ptr(68.66), CouponRate: ptr(24.0), CallDate: &callDate,
		CreditRating: ptr("ruBBB-"), RiskLevel: bonds.RiskLevelModerate,
		PrevVolumeRub: &vol, MaturityDate: &maturity,
	}
	scored := screening.ScoreBondsForProfile(
		[]bonds.BondRecord{callable, plain},
		screening.RiskProfileAggressive,
		14.5, 0.13,
		screening.DefaultDurationPolicy,
	)
	bySecid := map[string]bonds.BondRecord{}
	for _, b := range scored {
		bySecid[b.Secid] = b
	}
	if *bySecid["PLAIN"].Score <= *bySecid["CALL"].Score {
		t.Fatal("expected PLAIN > CALL")
	}
}

func TestCallableBondHasStrongerRiskPenaltyThanPlain(t *testing.T) {
	callDate := time.Date(2026, 10, 6, 0, 0, 0, 0, time.UTC)
	callable := bonds.BondRecord{
		Secid: "CALL", ISIN: "RU000CALL", Name: "CALL",
		CallDate: &callDate, RiskLevel: bonds.RiskLevelModerate, CreditRating: ptr("ruBBB-"),
	}
	plain := bonds.BondRecord{
		Secid: "PLAIN", ISIN: "RU000PLAIN", Name: "PLAIN",
		RiskLevel: bonds.RiskLevelModerate, CreditRating: ptr("ruBBB-"),
	}
	if screening.CalcRiskScore(&callable) >= screening.CalcRiskScore(&plain) {
		t.Fatal("callable bond must have lower risk score")
	}
	diff := screening.CalcRiskScore(&plain) - screening.CalcRiskScore(&callable)
	approxEqual(t, diff, 12.0)
}
