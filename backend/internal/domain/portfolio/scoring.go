package portfolio

import (
	"math"
	"sort"

	"github.com/tonatos/instrumenta/backend/internal/domain/bonds"
)

const (
	keyRateDefault = 14.5
	taxRateDefault = 0.13

	ytmScalePercentile       = 0.95
	distressSpreadStartPP    = 28.0
	distressYTMDecayStartPP  = 35.0
	distressSpreadFullPP     = 50.0
	distressPenaltyMax       = 40.0
	igDistressSpreadBonusPP  = 12.0
	igMinRatingOrdinal       = 3
	aggressiveBoredomSpread  = 14.0
	aggressiveBoredomPenaltyPts = 22.0
	aggressiveJunkSpread        = 28.0
	aggressiveJunkPenaltyPts    = 50.0
	callTrapPenalty          = 12.0
	unratedPenalty           = -25.0
	liqFloorRub              = 500_000.0
	liqGoodRub               = 10_000_000.0
)

var riskBase = map[bonds.RiskLevel]float64{
	bonds.RiskLevelLow: 80, bonds.RiskLevelModerate: 55,
	bonds.RiskLevelHigh: 25, bonds.RiskLevelUnknown: 45,
}

var ratingBonuses = []struct {
	threshold int
	bonus     float64
}{
	{12, 20}, {11, 16}, {10, 12}, {9, 8}, {8, 4}, {7, 0},
	{6, -5}, {5, -8}, {4, -12}, {3, -16}, {2, -20}, {1, -22}, {0, -25},
}

var profileWeights = map[RiskProfile][3]float64{
	RiskProfileConservative: {0.20, 0.60, 0.20},
	RiskProfileNormal:       {0.30, 0.50, 0.20},
	RiskProfileAggressive:   {0.60, 0.25, 0.15},
}

func ratingBonus(rating *string) float64 {
	if rating == nil {
		return unratedPenalty
	}
	ord, ok := bonds.RatingOrder[*rating]
	if !ok {
		return 0
	}
	for _, rb := range ratingBonuses {
		if ord >= rb.threshold {
			return rb.bonus
		}
	}
	return -25
}

func calcYTMScore(ytmNet, riskFreeNet, maxSpread float64) float64 {
	spread := ytmNet - riskFreeNet
	if spread <= 0 {
		return 0
	}
	if maxSpread <= 0 {
		return 50
	}
	peakSpread := math.Min(spread, distressSpreadStartPP)
	peakScore := math.Min(100, peakSpread/maxSpread*100)
	if spread <= distressYTMDecayStartPP {
		return peakScore
	}
	if spread >= distressSpreadFullPP {
		return 0
	}
	decay := (spread - distressYTMDecayStartPP) / (distressSpreadFullPP - distressYTMDecayStartPP)
	return math.Max(0, peakScore*(1-decay))
}

func scoringYTMNet(b bonds.BondRecord, riskFreeNet, afterTaxMult float64) *float64 {
	if b.YTMNet == nil {
		return nil
	}
	if b.CallDate == nil {
		return b.YTMNet
	}
	if b.CouponRate == nil {
		v := riskFreeNet
		return &v
	}
	v := math.Min(*b.YTMNet, *b.CouponRate*afterTaxMult)
	return &v
}

func ytmScaleReference(values []float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	if len(values) == 1 {
		return &values[0]
	}
	sorted := append([]float64(nil), values...)
	sort.Float64s(sorted)
	idx := int(math.Round(ytmScalePercentile*100)) - 1
	if idx < 0 {
		idx = 0
	}
	if idx >= len(sorted) {
		idx = len(sorted) - 1
	}
	return &sorted[idx]
}

func calcRiskScore(b bonds.BondRecord) float64 {
	base := riskBase[bonds.RiskLevelUnknown]
	if v, ok := riskBase[b.RiskLevel]; ok {
		base = v
	}
	penalties := 0.0
	if b.AmortizationFlag {
		penalties += 5
	}
	if b.CouponType == bonds.CouponTypeVariable {
		penalties += 8
	}
	if b.SubordinatedFlag {
		penalties += 30
	}
	if b.CallDate != nil {
		penalties += callTrapPenalty
	}
	score := base - penalties + ratingBonus(b.CreditRating)
	return math.Max(0, math.Min(100, score))
}

func distressSpreadStart(b bonds.BondRecord) float64 {
	if b.CreditRating != nil {
		if ord, ok := bonds.RatingOrder[*b.CreditRating]; ok && ord >= igMinRatingOrdinal {
			return distressSpreadStartPP + igDistressSpreadBonusPP
		}
	}
	return distressSpreadStartPP
}

func calcDistressPenalty(b bonds.BondRecord, ytmNet, riskFreeNet float64) float64 {
	spread := ytmNet - riskFreeNet
	start := distressSpreadStart(b)
	if spread <= start {
		return 0
	}
	span := distressSpreadFullPP - start
	if span <= 0 {
		return distressPenaltyMax
	}
	return math.Min(1, (spread-start)/span) * distressPenaltyMax
}

func calcLiquidityScore(volumeRub float64) float64 {
	if volumeRub <= liqFloorRub {
		return 0
	}
	if volumeRub >= liqGoodRub {
		return 100
	}
	logSpan := math.Log10(liqGoodRub) - math.Log10(liqFloorRub)
	if logSpan <= 0 {
		return 0
	}
	frac := (math.Log10(volumeRub) - math.Log10(liqFloorRub)) / logSpan
	return math.Min(100, math.Max(0, frac*100))
}

func finalRiskScore(b bonds.BondRecord, riskFreeNet, afterTaxMult float64) float64 {
	penalty := 0.0
	if v := scoringYTMNet(b, riskFreeNet, afterTaxMult); v != nil {
		penalty = calcDistressPenalty(b, *v, riskFreeNet)
	}
	return math.Max(0, calcRiskScore(b)-penalty)
}

func aggressiveBoredomPenalty(ytmNet, riskFreeNet float64) float64 {
	spread := ytmNet - riskFreeNet
	if spread >= aggressiveBoredomSpread {
		return 0
	}
	return math.Max(0, (1-spread/aggressiveBoredomSpread)*aggressiveBoredomPenaltyPts)
}

func aggressiveJunkPenalty(b bonds.BondRecord, ytmNet, riskFreeNet float64) float64 {
	spread := ytmNet - riskFreeNet
	if spread <= aggressiveJunkSpread {
		return 0
	}
	if b.CreditRating != nil {
		if ord, ok := bonds.RatingOrder[*b.CreditRating]; ok && ord >= igMinRatingOrdinal {
			return 0
		}
	}
	span := distressSpreadFullPP - aggressiveJunkSpread
	if span <= 0 {
		return aggressiveJunkPenaltyPts
	}
	return math.Min(1, (spread-aggressiveJunkSpread)/span) * aggressiveJunkPenaltyPts
}

func compositeForProfile(b bonds.BondRecord, profile RiskProfile, riskFreeNet, afterTaxMult float64) float64 {
	w := profileWeights[profile]
	ytm, risk, liq := deref(b.YTMScore), deref(b.RiskScore), deref(b.LiquidityScore)
	score := ytm*w[0] + risk*w[1] + liq*w[2]
	if profile == RiskProfileAggressive {
		boredom := 0.0
		if v := scoringYTMNet(b, riskFreeNet, afterTaxMult); v != nil {
			boredom = *v
		} else if b.YTMNet != nil {
			boredom = *b.YTMNet
		}
		score = math.Max(0, score-aggressiveBoredomPenalty(boredom, riskFreeNet)-aggressiveJunkPenalty(b, boredom, riskFreeNet))
	}
	return score
}

func deref(p *float64) float64 {
	if p == nil {
		return 0
	}
	return *p
}

func prepareBondScoreComponents(bs []bonds.BondRecord, keyRate, taxRate float64) (riskFreeNet, afterTaxMult float64) {
	afterTaxMult = 1 - taxRate
	riskFreeNet = keyRate * afterTaxMult
	for i := range bs {
		if bs[i].YTM != nil {
			v := *bs[i].YTM * afterTaxMult
			bs[i].YTMNet = &v
		}
	}
	var ytmValues []float64
	for _, b := range bs {
		if v := scoringYTMNet(b, riskFreeNet, afterTaxMult); v != nil {
			ytmValues = append(ytmValues, *v)
		}
	}
	scaleYTM := riskFreeNet
	if ref := ytmScaleReference(ytmValues); ref != nil {
		scaleYTM = *ref
	}
	maxSpread := math.Max(scaleYTM-riskFreeNet, 0)
	for i := range bs {
		ytmScore := 0.0
		if v := scoringYTMNet(bs[i], riskFreeNet, afterTaxMult); v != nil {
			ytmScore = calcYTMScore(*v, riskFreeNet, maxSpread)
		}
		bs[i].YTMScore = &ytmScore
		riskScore := finalRiskScore(bs[i], riskFreeNet, afterTaxMult)
		bs[i].RiskScore = &riskScore
		liqScore := calcLiquidityScore(bs[i].FilterVolumeRub())
		bs[i].LiquidityScore = &liqScore
	}
	return riskFreeNet, afterTaxMult
}

func durationScaleYears(bs []bonds.BondRecord, dp DurationPolicy) float64 {
	var max float64
	for _, b := range bs {
		if d := RateSensitiveDuration(b, dp); d != nil && *d > max {
			max = *d
		}
	}
	return max
}

func durationAdjustmentForBond(b bonds.BondRecord, dp DurationPolicy, durationScale float64) float64 {
	if dp.DurationScoreWeight <= 0 || dp.RateScenario == RateScenarioHold || durationScale <= 0 {
		return 0
	}
	var dur float64
	if d := RateSensitiveDuration(b, dp); d != nil {
		dur = *d
	} else {
		return 0
	}
	norm := math.Min(1, math.Max(0, dur/durationScale))
	factor := norm
	if dp.RateScenario == RateScenarioHike {
		factor = 1 - norm
	}
	return factor * dp.DurationScoreWeight * 100
}

// ScoreBondsForProfile scores and ranks bonds for one risk profile.
func ScoreBondsForProfile(
	input []bonds.BondRecord,
	profile RiskProfile,
	keyRate, taxRate float64,
	durationPolicy DurationPolicy,
) []bonds.BondRecord {
	if len(input) == 0 {
		return nil
	}
	bs := append([]bonds.BondRecord(nil), input...)
	riskFreeNet, afterTaxMult := prepareBondScoreComponents(bs, keyRate, taxRate)
	durationScale := durationScaleYears(bs, durationPolicy)
	result := make([]bonds.BondRecord, 0, len(bs))
	for _, b := range bs {
		base := compositeForProfile(b, profile, riskFreeNet, afterTaxMult)
		score := math.Min(100, math.Max(0, base+durationAdjustmentForBond(b, durationPolicy, durationScale)))
		b.ProfileScores = map[string]float64{string(profile): score}
		b.Score = &score
		result = append(result, b)
	}
	sort.Slice(result, func(i, j int) bool {
		return deref(result[i].Score) > deref(result[j].Score)
	})
	return result
}
