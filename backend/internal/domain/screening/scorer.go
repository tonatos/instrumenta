// Package screening implements the composite bond scoring model.
package screening

import (
	"math"
	"sort"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

// Defaults; overridden via env / app config.
const (
	KeyRateDefault = 14.5
	TaxRateDefault = 0.13
)

const (
	ytmScalePercentile            = 0.95
	distressSpreadStartPP         = 28.0
	distressYTMDecayStartPP       = 35.0
	distressSpreadFullPP          = 50.0
	distressPenaltyMax            = 40.0
	igDistressSpreadBonusPP       = 12.0
	igMinRatingOrdinal            = 3
	aggressiveBoredomSpreadPP     = 14.0
	aggressiveBoredomPenaltyMax   = 22.0
	aggressiveJunkSpreadPP        = 28.0
	aggressiveJunkPenaltyMax      = 50.0
	callTrapPenalty               = 12.0
	unratedPenalty                = -25.0
	liqFloorRub                   = 500_000.0
	liqGoodRub                    = 10_000_000.0
)

var riskBase = map[bonds.RiskLevel]float64{
	bonds.RiskLevelLow:      80.0,
	bonds.RiskLevelModerate: 55.0,
	bonds.RiskLevelHigh:     25.0,
	bonds.RiskLevelUnknown:  45.0,
}

var ratingBonuses = []struct {
	threshold int
	bonus     float64
}{
	{12, 20.0},
	{11, 16.0},
	{10, 12.0},
	{9, 8.0},
	{8, 4.0},
	{7, 0.0},
	{6, -5.0},
	{5, -8.0},
	{4, -12.0},
	{3, -16.0},
	{2, -20.0},
	{1, -22.0},
	{0, -25.0},
}

var allRiskProfiles = []RiskProfile{
	RiskProfileConservative,
	RiskProfileNormal,
	RiskProfileAggressive,
}

// RiskProfile selects scoring weights.
type RiskProfile string

const (
	RiskProfileConservative RiskProfile = "conservative"
	RiskProfileNormal       RiskProfile = "normal"
	RiskProfileAggressive   RiskProfile = "aggressive"
)

// RateScenario influences duration preference in scoring.
type RateScenario string

const (
	RateScenarioHold RateScenario = "hold"
	RateScenarioCut  RateScenario = "cut"
	RateScenarioHike RateScenario = "hike"
)

// DurationPolicy controls duration adjustments in composite score.
type DurationPolicy struct {
	MaxWeightedDurationYears *float64
	TargetDurationYears      *float64
	DurationScoreWeight      float64
	RateScenario             RateScenario
	FloaterRateDurationYears float64
}

// DefaultDurationPolicy is the noop duration policy.
var DefaultDurationPolicy = DurationPolicy{
	RateScenario: RateScenarioHold,
}

var profileWeights = map[RiskProfile][3]float64{
	RiskProfileConservative: {0.20, 0.60, 0.20},
	RiskProfileNormal:       {0.30, 0.50, 0.20},
	RiskProfileAggressive:   {0.60, 0.25, 0.15},
}

// CalcYTMScore normalizes excess yield above risk-free (after tax) to [0, 100].
func CalcYTMScore(ytmNet *float64, riskFreeNet, maxSpread float64) float64 {
	if ytmNet == nil {
		return 0.0
	}
	spread := *ytmNet - riskFreeNet
	if spread <= 0 {
		return 0.0
	}
	if maxSpread <= 0 {
		return 50.0
	}

	peakSpread := math.Min(spread, distressSpreadStartPP)
	peakScore := math.Min(100.0, peakSpread/maxSpread*100.0)
	if spread <= distressYTMDecayStartPP {
		return peakScore
	}
	if spread >= distressSpreadFullPP {
		return 0.0
	}
	decayFrac := (spread - distressYTMDecayStartPP) / (distressSpreadFullPP - distressYTMDecayStartPP)
	return math.Max(0.0, peakScore*(1.0-decayFrac))
}

// ScoringYTMNet returns YTM net for scoring (caps callable bonds at coupon yield).
func ScoringYTMNet(bond *bonds.BondRecord, riskFreeNet, afterTaxMultiplier float64) *float64 {
	if bond.YTMNet == nil {
		return nil
	}
	if bond.CallDate == nil {
		return bond.YTMNet
	}
	if bond.CouponRate == nil {
		v := riskFreeNet
		return &v
	}
	couponNet := *bond.CouponRate * afterTaxMultiplier
	v := math.Min(*bond.YTMNet, couponNet)
	return &v
}

// YTMScaleReference returns the YTM percentile used as the upper anchor of the score scale.
func YTMScaleReference(ytmValues []float64) *float64 {
	if len(ytmValues) == 0 {
		return nil
	}
	if len(ytmValues) == 1 {
		v := ytmValues[0]
		return &v
	}
	sorted := make([]float64, len(ytmValues))
	copy(sorted, ytmValues)
	sort.Float64s(sorted)

	n := 100
	cutIndex := int(math.Round(ytmScalePercentile*100)) - 1
	m := float64(len(sorted) - 1)
	pos := float64(cutIndex+1) * m / float64(n)
	idx := int(pos)
	frac := pos - float64(idx)
	var result float64
	if frac == 0.0 {
		result = sorted[idx]
	} else {
		result = sorted[idx]*(1.0-frac) + sorted[idx+1]*frac
	}
	return &result
}

// CalcRiskScore returns risk quality score [0, 100]: higher means safer.
func CalcRiskScore(bond *bonds.BondRecord) float64 {
	base, ok := riskBase[bond.RiskLevel]
	if !ok {
		base = riskBase[bonds.RiskLevelUnknown]
	}

	penalties := 0.0
	if bond.AmortizationFlag {
		penalties += 5.0
	}
	if bond.CouponType == bonds.CouponTypeVariable {
		penalties += 8.0
	}
	if bond.SubordinatedFlag {
		penalties += 30.0
	}
	if bond.CallDate != nil {
		penalties += callTrapPenalty
	}

	score := base - penalties + ratingBonus(bond.CreditRating)
	return math.Max(0.0, math.Min(100.0, score))
}

func ratingBonus(rating *string) float64 {
	if rating == nil {
		return unratedPenalty
	}
	ordinal, ok := bonds.RatingOrder[*rating]
	if !ok {
		return 0.0
	}
	for _, rb := range ratingBonuses {
		if ordinal >= rb.threshold {
			return rb.bonus
		}
	}
	return -25.0
}

func distressSpreadStart(bond *bonds.BondRecord) float64 {
	if bond.CreditRating != nil {
		if ordinal, ok := bonds.RatingOrder[*bond.CreditRating]; ok && ordinal >= igMinRatingOrdinal {
			return distressSpreadStartPP + igDistressSpreadBonusPP
		}
	}
	return distressSpreadStartPP
}

// CalcDistressPenalty returns penalty applied to risk_score when yield spread signals distress.
func CalcDistressPenalty(bond *bonds.BondRecord, ytmNet *float64, riskFreeNet float64) float64 {
	ytm := 0.0
	if ytmNet != nil {
		ytm = *ytmNet
	}
	spread := ytm - riskFreeNet
	start := distressSpreadStart(bond)
	if spread <= start {
		return 0.0
	}
	span := distressSpreadFullPP - start
	if span <= 0 {
		return distressPenaltyMax
	}
	frac := (spread - start) / span
	return math.Min(1.0, frac) * distressPenaltyMax
}

// CalcLiquidityScore returns logarithmic liquidity score [0, 100] on absolute volume anchors.
func CalcLiquidityScore(volumeRub *float64) float64 {
	if volumeRub == nil || *volumeRub <= 0 {
		return 0.0
	}
	v := *volumeRub
	if v <= liqFloorRub {
		return 0.0
	}
	if v >= liqGoodRub {
		return 100.0
	}
	logSpan := math.Log10(liqGoodRub) - math.Log10(liqFloorRub)
	if logSpan <= 0 {
		return 0.0
	}
	frac := (math.Log10(v) - math.Log10(liqFloorRub)) / logSpan
	return math.Min(100.0, math.Max(0.0, frac*100.0))
}

func finalRiskScore(bond *bonds.BondRecord, riskFreeNet, afterTaxMultiplier float64) float64 {
	scoringYTM := ScoringYTMNet(bond, riskFreeNet, afterTaxMultiplier)
	return math.Max(0.0, CalcRiskScore(bond)-CalcDistressPenalty(bond, scoringYTM, riskFreeNet))
}

// CalcAggressiveBoredomPenalty is the composite-score penalty for low-yield bonds in aggressive profile.
func CalcAggressiveBoredomPenalty(ytmNet *float64, riskFreeNet float64) float64 {
	ytm := 0.0
	if ytmNet != nil {
		ytm = *ytmNet
	}
	spread := ytm - riskFreeNet
	if spread >= aggressiveBoredomSpreadPP {
		return 0.0
	}
	if aggressiveBoredomSpreadPP <= 0 {
		return 0.0
	}
	frac := 1.0 - spread/aggressiveBoredomSpreadPP
	return math.Max(0.0, frac) * aggressiveBoredomPenaltyMax
}

// CalcAggressiveJunkPenalty is the composite-score penalty for sub-IG bonds with extreme yield spreads.
func CalcAggressiveJunkPenalty(bond *bonds.BondRecord, ytmNet *float64, riskFreeNet float64) float64 {
	ytm := 0.0
	if ytmNet != nil {
		ytm = *ytmNet
	}
	spread := ytm - riskFreeNet
	if spread <= aggressiveJunkSpreadPP {
		return 0.0
	}
	if bond.CreditRating != nil {
		if ordinal, ok := bonds.RatingOrder[*bond.CreditRating]; ok && ordinal >= igMinRatingOrdinal {
			return 0.0
		}
	}
	span := distressSpreadFullPP - aggressiveJunkSpreadPP
	if span <= 0 {
		return aggressiveJunkPenaltyMax
	}
	frac := math.Min(1.0, (spread-aggressiveJunkSpreadPP)/span)
	return frac * aggressiveJunkPenaltyMax
}

func compositeForProfile(
	bond *bonds.BondRecord,
	profile RiskProfile,
	riskFreeNet, afterTaxMultiplier float64,
) float64 {
	weights := profileWeights[profile]
	ytmScore := 0.0
	if bond.YTMScore != nil {
		ytmScore = *bond.YTMScore
	}
	riskScore := 0.0
	if bond.RiskScore != nil {
		riskScore = *bond.RiskScore
	}
	liqScore := 0.0
	if bond.LiquidityScore != nil {
		liqScore = *bond.LiquidityScore
	}
	score := ytmScore*weights[0] + riskScore*weights[1] + liqScore*weights[2]
	if profile == RiskProfileAggressive {
		scoringYTM := ScoringYTMNet(bond, riskFreeNet, afterTaxMultiplier)
		boredomYTM := scoringYTM
		if boredomYTM == nil {
			boredomYTM = bond.YTMNet
		}
		score = math.Max(0.0, score-
			CalcAggressiveBoredomPenalty(boredomYTM, riskFreeNet)-
			CalcAggressiveJunkPenalty(bond, boredomYTM, riskFreeNet))
	}
	return score
}

func prepareBondScoreComponents(
	bondList []*bonds.BondRecord,
	keyRate, taxRate float64,
) (riskFreeNet, afterTaxMultiplier, maxSpread float64) {
	afterTaxMultiplier = 1.0 - taxRate
	riskFreeNet = keyRate * afterTaxMultiplier

	for _, bond := range bondList {
		if bond.YTM != nil {
			v := *bond.YTM * afterTaxMultiplier
			bond.YTMNet = &v
		} else {
			bond.YTMNet = nil
		}
	}

	var ytmValues []float64
	for _, b := range bondList {
		if net := ScoringYTMNet(b, riskFreeNet, afterTaxMultiplier); net != nil {
			ytmValues = append(ytmValues, *net)
		}
	}

	scaleYTMNet := YTMScaleReference(ytmValues)
	if scaleYTMNet == nil {
		scaleYTMNet = &riskFreeNet
	}
	maxSpread = math.Max(*scaleYTMNet-riskFreeNet, 0.0)

	for _, bond := range bondList {
		scoringYTM := ScoringYTMNet(bond, riskFreeNet, afterTaxMultiplier)
		ytmScore := CalcYTMScore(scoringYTM, riskFreeNet, maxSpread)
		bond.YTMScore = &ytmScore
		riskScore := finalRiskScore(bond, riskFreeNet, afterTaxMultiplier)
		bond.RiskScore = &riskScore
		liqScore := CalcLiquidityScore(bonds.FloatPtr(bond.FilterVolumeRub()))
		bond.LiquidityScore = &liqScore
	}
	return riskFreeNet, afterTaxMultiplier, maxSpread
}

// ScoreBondsAllProfiles computes profile-aware composite scores for all bonds.
func ScoreBondsAllProfiles(bondList []bonds.BondRecord, keyRate, taxRate float64) []bonds.BondRecord {
	if len(bondList) == 0 {
		return nil
	}

	mutable := make([]bonds.BondRecord, len(bondList))
	copy(mutable, bondList)
	ptrs := make([]*bonds.BondRecord, len(mutable))
	for i := range mutable {
		ptrs[i] = &mutable[i]
	}

	riskFreeNet, afterTaxMultiplier, _ := prepareBondScoreComponents(ptrs, keyRate, taxRate)

	for i := range mutable {
		profileScores := make(map[string]float64, len(allRiskProfiles))
		for _, profile := range allRiskProfiles {
			profileScores[string(profile)] = compositeForProfile(
				&mutable[i], profile, riskFreeNet, afterTaxMultiplier,
			)
		}
		mutable[i].ProfileScores = profileScores
		normalScore := profileScores[string(RiskProfileNormal)]
		mutable[i].Score = &normalScore
	}

	sort.Slice(mutable, func(i, j int) bool {
		si, sj := 0.0, 0.0
		if mutable[i].Score != nil {
			si = *mutable[i].Score
		}
		if mutable[j].Score != nil {
			sj = *mutable[j].Score
		}
		return si > sj
	})
	return mutable
}

// CalcDurationAdjustment returns duration bonus/penalty for a rate scenario.
func CalcDurationAdjustment(
	durationYears *float64,
	scaleYears float64,
	scenario RateScenario,
	weight float64,
) float64 {
	if weight <= 0 || scenario == RateScenarioHold {
		return 0.0
	}
	if durationYears == nil || scaleYears <= 0 {
		return 0.0
	}
	norm := math.Min(1.0, math.Max(0.0, *durationYears/scaleYears))
	factor := norm
	if scenario == RateScenarioHike {
		factor = 1.0 - norm
	}
	return factor * weight * 100.0
}

// CalcTargetDurationAdjustment returns soft bonus for closeness to target duration.
func CalcTargetDurationAdjustment(
	durationYears *float64,
	targetYears *float64,
	scaleYears, weight float64,
) float64 {
	if weight <= 0 || targetYears == nil {
		return 0.0
	}
	if durationYears == nil || scaleYears <= 0 {
		return 0.0
	}
	distance := math.Abs(*durationYears-*targetYears) / scaleYears
	closeness := math.Max(0.0, 1.0-distance)
	return closeness * weight * 50.0
}

// RateSensitiveDuration returns duration for rate risk (floaters use policy floater duration).
func RateSensitiveDuration(bond *bonds.BondRecord, durationPolicy DurationPolicy) *float64 {
	if bond.IsFloatingCoupon() {
		v := durationPolicy.FloaterRateDurationYears
		return &v
	}
	return bond.DurationYears()
}

// DurationScaleYears returns max rate-sensitive duration across bonds.
func DurationScaleYears(bondList []bonds.BondRecord, durationPolicy DurationPolicy) float64 {
	var maxDur float64
	for i := range bondList {
		if d := RateSensitiveDuration(&bondList[i], durationPolicy); d != nil && *d > maxDur {
			maxDur = *d
		}
	}
	return maxDur
}

func durationAdjustmentTotal(
	bond *bonds.BondRecord,
	durationScale float64,
	durationPolicy DurationPolicy,
) float64 {
	weight := durationPolicy.DurationScoreWeight
	sensitiveDuration := RateSensitiveDuration(bond, durationPolicy)
	return CalcDurationAdjustment(
		sensitiveDuration,
		durationScale,
		durationPolicy.RateScenario,
		weight,
	) + CalcTargetDurationAdjustment(
		sensitiveDuration,
		durationPolicy.TargetDurationYears,
		durationScale,
		weight,
	)
}

// DurationAdjustmentForBond returns duration bonus/penalty for one bond.
func DurationAdjustmentForBond(
	bond *bonds.BondRecord,
	durationPolicy DurationPolicy,
	durationScale float64,
) float64 {
	return durationAdjustmentTotal(bond, durationScale, durationPolicy)
}

// ResolveProfileScores applies duration adjustment without mutating base profile scores on bond.
func ResolveProfileScores(
	bond *bonds.BondRecord,
	durationPolicy DurationPolicy,
	durationScale float64,
) map[string]float64 {
	base := bond.ProfileScores
	if len(base) == 0 {
		return map[string]float64{}
	}
	adjustment := DurationAdjustmentForBond(bond, durationPolicy, durationScale)
	if adjustment == 0.0 {
		out := make(map[string]float64, len(base))
		for k, v := range base {
			out[k] = v
		}
		return out
	}
	out := make(map[string]float64, len(base))
	for key, value := range base {
		out[key] = math.Min(100.0, math.Max(0.0, value+adjustment))
	}
	return out
}

// ResolvedActiveScore returns profile score including duration adjustment.
func ResolvedActiveScore(
	bond *bonds.BondRecord,
	profile RiskProfile,
	durationPolicy DurationPolicy,
	durationScale float64,
) *float64 {
	scores := ResolveProfileScores(bond, durationPolicy, durationScale)
	if len(scores) > 0 {
		if v, ok := scores[string(profile)]; ok {
			return &v
		}
	}
	return bond.Score
}

// SortBondsByResolvedScore sorts bonds by profile-aware score including duration.
func SortBondsByResolvedScore(
	bondList []bonds.BondRecord,
	profile RiskProfile,
	durationPolicy DurationPolicy,
) []bonds.BondRecord {
	out := make([]bonds.BondRecord, len(bondList))
	copy(out, bondList)
	durationScale := DurationScaleYears(out, durationPolicy)
	sort.Slice(out, func(i, j int) bool {
		si, sj := 0.0, 0.0
		if v := ResolvedActiveScore(&out[i], profile, durationPolicy, durationScale); v != nil {
			si = *v
		}
		if v := ResolvedActiveScore(&out[j], profile, durationPolicy, durationScale); v != nil {
			sj = *v
		}
		return si > sj
	})
	return out
}

// ApplyDurationScoring returns bonds with resolved profile scores and active score.
func ApplyDurationScoring(
	bondList []bonds.BondRecord,
	durationPolicy DurationPolicy,
	activeProfile RiskProfile,
) []bonds.BondRecord {
	if durationPolicy.RateScenario == RateScenarioHold &&
		durationPolicy.DurationScoreWeight <= 0 &&
		durationPolicy.TargetDurationYears == nil {
		out := make([]bonds.BondRecord, len(bondList))
		copy(out, bondList)
		return out
	}

	durationScale := DurationScaleYears(bondList, durationPolicy)
	result := make([]bonds.BondRecord, len(bondList))
	for i, bond := range bondList {
		resolved := ResolveProfileScores(&bond, durationPolicy, durationScale)
		active := bond.Score
		if v, ok := resolved[string(activeProfile)]; ok {
			active = &v
		}
		bond.ProfileScores = resolved
		bond.Score = active
		result[i] = bond
	}
	sort.Slice(result, func(i, j int) bool {
		si, sj := 0.0, 0.0
		if result[i].Score != nil {
			si = *result[i].Score
		}
		if result[j].Score != nil {
			sj = *result[j].Score
		}
		return si > sj
	})
	return result
}

// ScoreBondsForProfile scores bonds for a single profile on the supplied subset.
func ScoreBondsForProfile(
	bondList []bonds.BondRecord,
	profile RiskProfile,
	keyRate, taxRate float64,
	durationPolicy DurationPolicy,
) []bonds.BondRecord {
	if len(bondList) == 0 {
		return nil
	}

	mutable := make([]bonds.BondRecord, len(bondList))
	copy(mutable, bondList)
	ptrs := make([]*bonds.BondRecord, len(mutable))
	for i := range mutable {
		ptrs[i] = &mutable[i]
	}

	riskFreeNet, afterTaxMultiplier, _ := prepareBondScoreComponents(ptrs, keyRate, taxRate)
	durationScale := DurationScaleYears(mutable, durationPolicy)

	for i := range mutable {
		baseScore := compositeForProfile(&mutable[i], profile, riskFreeNet, afterTaxMultiplier)
		mutable[i].ProfileScores = map[string]float64{string(profile): baseScore}
		resolved := ResolveProfileScores(&mutable[i], durationPolicy, durationScale)
		if v, ok := resolved[string(profile)]; ok {
			mutable[i].Score = &v
		} else {
			mutable[i].Score = &baseScore
		}
		mutable[i].ProfileScores = resolved
	}

	sort.Slice(mutable, func(i, j int) bool {
		si, sj := 0.0, 0.0
		if mutable[i].Score != nil {
			si = *mutable[i].Score
		}
		if mutable[j].Score != nil {
			sj = *mutable[j].Score
		}
		return si > sj
	})
	return mutable
}
