package portfolio

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/screening"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

const (
	conservativeMinRating = 7  // ruA
	normalMinRating       = 6  // ruA-
	aggressiveMinRating   = 0  // ruBB-
)

type BondSelectionResult struct {
	Bonds                  []bonds.BondRecord
	FallbackNote           string
	EffectiveProfileFilter *RiskProfile
}

type MaturityIndex struct {
	dates []time.Time
	bonds []bonds.BondRecord
}

func BuildMaturityIndex(universe []bonds.BondRecord) MaturityIndex {
	var dated []struct {
		d time.Time
		b bonds.BondRecord
	}
	for _, bond := range universe {
		end := bond.MaturityDate
		if end == nil {
			end = bond.OfferDate
		}
		if end != nil {
			dated = append(dated, struct {
				d time.Time
				b bonds.BondRecord
			}{*end, bond})
		}
	}
	sort.Slice(dated, func(i, j int) bool { return dated[i].d.Before(dated[j].d) })
	idx := MaturityIndex{}
	for _, item := range dated {
		idx.dates = append(idx.dates, item.d)
		idx.bonds = append(idx.bonds, item.b)
	}
	return idx
}

func (m MaturityIndex) BondsBetween(minDate, maxDate time.Time) []bonds.BondRecord {
	if len(m.dates) == 0 {
		return nil
	}
	left := sort.Search(len(m.dates), func(i int) bool { return !m.dates[i].Before(minDate) })
	right := sort.Search(len(m.dates), func(i int) bool { return m.dates[i].After(maxDate) })
	return append([]bonds.BondRecord(nil), m.bonds[left:right]...)
}

type SelectionOptions struct {
	MaturityIndex *MaturityIndex
	RankedCache   map[string]BondSelectionResult
}

func HasUsablePrice(b bonds.BondRecord) bool {
	p := b.PricePerLotRub()
	return p != nil && *p > 0
}

func APITradableFilter(bs []bonds.BondRecord) []bonds.BondRecord {
	var out []bonds.BondRecord
	for _, b := range bs {
		if b.APITradeAvailableFlag != nil && *b.APITradeAvailableFlag {
			out = append(out, b)
		}
	}
	return out
}

func ratingOrdinal(b bonds.BondRecord) *int {
	if b.CreditRating == nil {
		return nil
	}
	if ord, ok := bonds.RatingOrder[*b.CreditRating]; ok {
		return &ord
	}
	return nil
}

func RiskProfileFilter(bs []bonds.BondRecord, profile RiskProfile) []bonds.BondRecord {
	var result []bonds.BondRecord
	for _, bond := range bs {
		if bond.HasDefault || bond.HasTechnicalDefault {
			continue
		}
		ord := ratingOrdinal(bond)
		switch profile {
		case RiskProfileConservative:
			if bond.SubordinatedFlag || bond.RiskLevel == bonds.RiskLevelHigh || ord == nil || *ord < conservativeMinRating || bond.CallDate != nil {
				continue
			}
		case RiskProfileNormal:
			if bond.SubordinatedFlag || bond.RiskLevel == bonds.RiskLevelHigh || ord == nil || *ord < normalMinRating {
				continue
			}
		case RiskProfileAggressive:
			if ord != nil && *ord < aggressiveMinRating {
				continue
			}
		}
		result = append(result, bond)
	}
	return result
}

func PortfolioUniverseFilter(bs []bonds.BondRecord, p Portfolio) []bonds.BondRecord {
	filtered := RiskProfileFilter(bs, p.RiskProfile)
	if p.APITradeOnly {
		filtered = APITradableFilter(filtered)
	}
	return filtered
}

func fallbackSteps(profile RiskProfile) []*RiskProfile {
	switch profile {
	case RiskProfileAggressive:
		return []*RiskProfile{profilePtr(RiskProfileAggressive), profilePtr(RiskProfileNormal), nil}
	case RiskProfileConservative:
		return []*RiskProfile{profilePtr(RiskProfileConservative), profilePtr(RiskProfileNormal), nil}
	default:
		return []*RiskProfile{profilePtr(RiskProfileNormal), nil}
	}
}

func profilePtr(p RiskProfile) *RiskProfile { return &p }

func profilesTriedLabel(profile RiskProfile) string {
	if profile == RiskProfileNormal {
		return "«normal» и любую без дефолта"
	}
	return fmt.Sprintf("«%s», «normal» и любую без дефолта", profile)
}

func minMaturityDate(ctx BondSelectionContext, policy BondSelectionPolicy) time.Time {
	return shared.AddDays(ctx.PurchaseDate, policy.MinReplacementHorizonDays)
}

func maturityWindow(ctx BondSelectionContext, policy BondSelectionPolicy) string {
	minDate := minMaturityDate(ctx, policy)
	return fmt.Sprintf("[%s, %s]", shared.FormatDate(&minDate), shared.FormatDate(&ctx.HorizonDate))
}

func BondEligibilityReason(b bonds.BondRecord, ctx BondSelectionContext, policy BondSelectionPolicy, checkBudget bool) *string {
	if policy.ExcludeDefault && (b.HasDefault || b.HasTechnicalDefault) {
		msg := "дефолт / тех.дефолт"
		return &msg
	}
	if !HasUsablePrice(b) {
		msg := "нет рыночной цены"
		return &msg
	}
	if b.LastPrice != nil && *b.LastPrice < policy.MinCleanPricePct {
		msg := fmt.Sprintf("чистая цена %.1f%% < %.0f%% номинала", *b.LastPrice, policy.MinCleanPricePct)
		return &msg
	}
	if blocked := PutOfferBuyBlocked(b, ctx.PurchaseDate); blocked != nil {
		return blocked
	}
	end := b.MaturityDate
	if end == nil {
		end = b.OfferDate
	}
	if end == nil {
		msg := "нет даты погашения / оферты"
		return &msg
	}
	minMat := minMaturityDate(ctx, policy)
	if end.Before(minMat) {
		msg := fmt.Sprintf("погашение %s раньше окна (не ранее %s)", shared.FormatDate(end), shared.FormatDate(&minMat))
		return &msg
	}
	if end.After(ctx.HorizonDate) {
		msg := fmt.Sprintf("погашение %s позже горизонта %s", shared.FormatDate(end), shared.FormatDate(&ctx.HorizonDate))
		return &msg
	}
	if checkBudget && ctx.BudgetRub != nil {
		lotCost := 0.0
		if p := b.PricePerLotRub(); p != nil {
			lotCost = *p
		}
		if lotCost > *ctx.BudgetRub {
			msg := fmt.Sprintf("лот %s ₽ > бюджета %s ₽", shared.FormatNumber(lotCost, 0), shared.FormatNumber(*ctx.BudgetRub, 0))
			return &msg
		}
	}
	return nil
}

func EligibleBonds(
	universe []bonds.BondRecord,
	ctx BondSelectionContext,
	policy BondSelectionPolicy,
	profileStep *RiskProfile,
	checkBudget bool,
	opts *SelectionOptions,
) []bonds.BondRecord {
	var searchPool []bonds.BondRecord
	if opts != nil && opts.MaturityIndex != nil {
		searchPool = opts.MaturityIndex.BondsBetween(minMaturityDate(ctx, policy), ctx.HorizonDate)
	} else {
		searchPool = universe
	}
	var pool []bonds.BondRecord
	if profileStep != nil {
		pool = RiskProfileFilter(searchPool, *profileStep)
	} else {
		for _, b := range searchPool {
			if !policy.ExcludeDefault || (!b.HasDefault && !b.HasTechnicalDefault) {
				pool = append(pool, b)
			}
		}
	}
	if ctx.APITradeOnly {
		pool = APITradableFilter(pool)
	}
	var result []bonds.BondRecord
	for _, bond := range pool {
		if BondEligibilityReason(bond, ctx, policy, checkBudget) == nil {
			result = append(result, bond)
		}
	}
	return result
}

func RankBonds(
	candidates []bonds.BondRecord,
	universe []bonds.BondRecord,
	profile RiskProfile,
	keyRate, taxRate float64,
	dp DurationPolicy,
) []bonds.BondRecord {
	if len(candidates) == 0 {
		return nil
	}
	screenDP := toScreeningDurationPolicy(dp)
	screenProfile := screening.RiskProfile(profile)
	durationScale := screening.DurationScaleYears(universe, screenDP)

	byISIN := make(map[string]bonds.BondRecord, len(universe))
	for _, b := range universe {
		byISIN[b.ISIN] = b
	}

	result := make([]bonds.BondRecord, 0, len(candidates))
	for _, candidate := range candidates {
		bond := candidate
		if scored, ok := byISIN[candidate.ISIN]; ok && len(scored.ProfileScores) > 0 {
			bond = scored
		} else {
			fallback := screening.ScoreBondsForProfile(
				[]bonds.BondRecord{candidate},
				screenProfile,
				keyRate,
				taxRate,
				screenDP,
			)
			if len(fallback) > 0 {
				bond = fallback[0]
			}
		}
		resolved := screening.ResolveProfileScores(&bond, screenDP, durationScale)
		if score, ok := resolved[string(profile)]; ok {
			bond.Score = &score
			bond.ProfileScores = resolved
		}
		result = append(result, bond)
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

func toScreeningDurationPolicy(dp DurationPolicy) screening.DurationPolicy {
	return screening.DurationPolicy{
		RateScenario:             screening.RateScenario(dp.RateScenario),
		DurationScoreWeight:      dp.DurationScoreWeight,
		TargetDurationYears:      dp.TargetDurationYears,
		MaxWeightedDurationYears: dp.MaxWeightedDurationYears,
		FloaterRateDurationYears: dp.FloaterRateDurationYears,
	}
}

func fallbackNote(ctx BondSelectionContext, requested, effective *RiskProfile) string {
	if effective == nil || (requested != nil && *effective == *requested) {
		return ""
	}
	if *effective == RiskProfileNormal {
		return fmt.Sprintf(
			"профиль «%s» — нет кандидатов в окне [%s, %s]; выбрана бумага под NORMAL-профиль",
			ctx.Profile, shared.FormatDate(&ctx.PurchaseDate), shared.FormatDate(&ctx.HorizonDate),
		)
	}
	profiles := fmt.Sprintf("профиль «%s»", ctx.Profile)
	if ctx.Profile != RiskProfileNormal {
		profiles = profilesTriedLabel(ctx.Profile)
	}
	return profiles + " не дали кандидатов в окне; выбрана лучшая по скору бумага без профильных ограничений"
}

func ExplainSelectionFailure(universe []bonds.BondRecord, ctx BondSelectionContext, policy BondSelectionPolicy) string {
	profiles := profilesTriedLabel(ctx.Profile)
	if ctx.BudgetRub != nil && *ctx.BudgetRub <= 0 {
		return fmt.Sprintf("ожидаемый кэш %s ₽ ≤ 0", shared.FormatNumber(*ctx.BudgetRub, 0))
	}
	minMat := minMaturityDate(ctx, policy)
	window := maturityWindow(ctx, policy)
	if minMat.After(ctx.HorizonDate) {
		return fmt.Sprintf(
			"окно реинвестиции слишком узкое — покупка с %s, но мин. срок удержания %d дн. → погашение замены не ранее %s, а горизонт плана %s",
			shared.FormatDate(&ctx.PurchaseDate), policy.MinReplacementHorizonDays,
			shared.FormatDate(&minMat), shared.FormatDate(&ctx.HorizonDate),
		)
	}
	var inWindow []bonds.BondRecord
	var tooExpensive []struct {
		b    bonds.BondRecord
		cost float64
	}
	budget := ctx.BudgetRub
	steps := fallbackSteps(ctx.Profile)
	for _, profileStep := range steps {
		for _, bond := range EligibleBonds(universe, ctx, policy, profileStep, false, nil) {
			if budget != nil {
				lotCost := 0.0
				if p := bond.PricePerLotRub(); p != nil {
					lotCost = *p
				}
				if lotCost > *budget {
					tooExpensive = append(tooExpensive, struct {
						b    bonds.BondRecord
						cost float64
					}{bond, lotCost})
					continue
				}
			}
			inWindow = append(inWindow, bond)
		}
	}
	if len(inWindow) > 0 {
		return fmt.Sprintf("пробовали %s: в окне %s есть %d подходящих по сроку и бюджету бумаг(и), но выбрать не удалось", profiles, window, len(inWindow))
	}
	if len(tooExpensive) > 0 {
		minLot := tooExpensive[0].cost
		for _, te := range tooExpensive[1:] {
			minLot = math.Min(minLot, te.cost)
		}
		budgetLabel := "—"
		if budget != nil {
			budgetLabel = shared.FormatNumber(*budget, 0)
		}
		return fmt.Sprintf("пробовали %s: в окне %s есть %d бумаг(и), но мин. лот %s ₽ больше доступных %s ₽",
			profiles, window, len(tooExpensive), shared.FormatNumber(minLot, 0), budgetLabel)
	}
	suffix := "по заданным критериям"
	if budget != nil {
		suffix = fmt.Sprintf("при доступных %s ₽", shared.FormatNumber(*budget, 0))
	}
	return fmt.Sprintf("пробовали %s: в окне %s нет бумаг с погашением %s (с учётом цены, лота и пут-оферт)", profiles, window, suffix)
}

func rankedCacheKey(ctx BondSelectionContext, keyRate, taxRate float64, dp DurationPolicy) string {
	budget := "nil"
	if ctx.BudgetRub != nil {
		budget = fmt.Sprintf("%.0f", math.Round(*ctx.BudgetRub))
	}
	return fmt.Sprintf("%s|%s|%s|%s|%t|%.4f|%.4f|%s|%v",
		ctx.Profile, ctx.HorizonDate.Format("2006-01-02"), ctx.PurchaseDate.Format("2006-01-02"),
		budget, ctx.APITradeOnly, keyRate, taxRate, dp.RateScenario, dp.MaxWeightedDurationYears)
}

func SelectRankedBonds(
	universe []bonds.BondRecord,
	ctx BondSelectionContext,
	policy BondSelectionPolicy,
	keyRate, taxRate float64,
	dp DurationPolicy,
	opts *SelectionOptions,
) BondSelectionResult {
	if minMaturityDate(ctx, policy).After(ctx.HorizonDate) {
		return BondSelectionResult{}
	}
	cacheKey := rankedCacheKey(ctx, keyRate, taxRate, dp)
	if opts != nil && opts.RankedCache != nil {
		if cached, ok := opts.RankedCache[cacheKey]; ok {
			return cached
		}
	}
	for _, step := range fallbackSteps(ctx.Profile) {
		candidates := EligibleBonds(universe, ctx, policy, step, true, opts)
		if len(candidates) == 0 {
			continue
		}
		ranked := RankBonds(candidates, universe, ctx.Profile, keyRate, taxRate, dp)
		if len(ranked) == 0 {
			continue
		}
		req := ctx.Profile
		result := BondSelectionResult{Bonds: ranked, FallbackNote: fallbackNote(ctx, &req, step), EffectiveProfileFilter: step}
		if opts != nil {
			if opts.RankedCache == nil {
				opts.RankedCache = make(map[string]BondSelectionResult)
			}
			opts.RankedCache[cacheKey] = result
		}
		return result
	}
	empty := BondSelectionResult{}
	if opts != nil {
		if opts.RankedCache == nil {
			opts.RankedCache = make(map[string]BondSelectionResult)
		}
		opts.RankedCache[cacheKey] = empty
	}
	return empty
}

func SelectBestBond(
	universe []bonds.BondRecord,
	ctx BondSelectionContext,
	policy BondSelectionPolicy,
	keyRate, taxRate float64,
	dp DurationPolicy,
	opts *SelectionOptions,
) (*bonds.BondRecord, string) {
	if ctx.BudgetRub != nil && *ctx.BudgetRub <= 0 {
		return nil, ExplainSelectionFailure(universe, ctx, policy)
	}
	result := SelectRankedBonds(universe, ctx, policy, keyRate, taxRate, dp, opts)
	if len(result.Bonds) > 0 {
		return &result.Bonds[0], result.FallbackNote
	}
	return nil, ExplainSelectionFailure(universe, ctx, policy)
}
