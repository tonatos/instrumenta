package portfolio

import (
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

func SelectionContext(
	profile RiskProfile,
	horizonDate, purchaseDate time.Time,
	apiTradeOnly bool,
	budgetRub *float64,
) BondSelectionContext {
	return BondSelectionContext{
		Profile: profile, HorizonDate: horizonDate, PurchaseDate: purchaseDate,
		BudgetRub: budgetRub, APITradeOnly: apiTradeOnly,
	}
}

func ValidateReplacementBond(b bonds.BondRecord, slotPurchaseDate, horizon time.Time) *string {
	if b.MaturityDate == nil {
		msg := "у бумаги нет даты погашения"
		return &msg
	}
	if !b.MaturityDate.After(slotPurchaseDate) {
		msg := fmt.Sprintf(
			"бумага гасится %s, что НЕ позже даты покупки %s",
			shared.FormatDate(b.MaturityDate), shared.FormatDate(&slotPurchaseDate),
		)
		return &msg
	}
	daysRemaining := shared.DaysBetween(slotPurchaseDate, *b.MaturityDate)
	if daysRemaining < MinReplacementHorizonDays {
		msg := fmt.Sprintf(
			"до погашения %s осталось всего %d дн. (< MIN_REPLACEMENT_HORIZON_DAYS = %d)",
			shared.FormatDate(b.MaturityDate), daysRemaining, MinReplacementHorizonDays,
		)
		return &msg
	}
	if b.MaturityDate.After(horizon) {
		msg := fmt.Sprintf(
			"погашение %s позже горизонта %s — реинвест прервётся",
			shared.FormatDate(b.MaturityDate), shared.FormatDate(&horizon),
		)
		return &msg
	}
	if b.HasDefault || b.HasTechnicalDefault {
		msg := "у бумаги статус дефолта / тех.дефолта"
		return &msg
	}
	if blocked := PutOfferBuyBlocked(b, slotPurchaseDate); blocked != nil {
		return blocked
	}
	return nil
}

func EnrichReinvestmentSlot(
	slot ReinvestmentSlot,
	p Portfolio,
	universe []bonds.BondRecord,
	keyRate, taxRate float64,
) ReinvestmentSlot {
	universeByISIN := make(map[string]bonds.BondRecord)
	for _, b := range universe {
		universeByISIN[b.ISIN] = b
	}
	ctx := SelectionContext(p.RiskProfile, p.HorizonDate, slot.PurchaseDate(), p.APITradeOnly, &slot.ExpectedCashRub)
	ranked := SelectRankedBonds(universe, ctx, DefaultBondSelectionPolicy, keyRate, taxRate, DefaultDurationPolicy, nil)
	var candidates []map[string]any
	limit := len(ranked.Bonds)
	if limit > SlotCandidatesLimit {
		limit = SlotCandidatesLimit
	}
	for _, b := range ranked.Bonds[:limit] {
		candidates = append(candidates, map[string]any{
			"isin": b.ISIN, "name": b.Name, "score": b.Score, "ytm_net": b.YTMNet,
		})
	}
	status := SlotStatusOK
	var failureReason *string
	targetISIN := slot.EffectiveISIN()
	if targetISIN == nil {
		status = SlotStatusNoCandidate
		msg := ExplainSelectionFailure(universe, ctx, DefaultBondSelectionPolicy)
		failureReason = &msg
	} else {
		targetBond, ok := universeByISIN[*targetISIN]
		if !ok || !HasUsablePrice(targetBond) {
			status = SlotStatusInvalidSelection
			msg := fmt.Sprintf("бумага %s отсутствует в актуальном универсе или нет рыночной цены", *targetISIN)
			failureReason = &msg
		} else if invalid := ValidateReplacementBond(targetBond, slot.PurchaseDate(), p.HorizonDate); invalid != nil {
			status = SlotStatusInvalidSelection
			failureReason = invalid
		} else if lotCost := targetBond.PricePerLotRub(); lotCost != nil && *lotCost > 0 && slot.ExpectedCashRub < *lotCost {
			status = SlotStatusInsufficientCash
			msg := fmt.Sprintf("ожидаемого кэша (%.0f ₽) не хватает на 1 лот %s (%.0f ₽)", slot.ExpectedCashRub, targetBond.Name, *lotCost)
			failureReason = &msg
		}
	}
	return ReinvestmentSlot{
		TriggerDate: slot.TriggerDate, TriggerReason: slot.TriggerReason,
		ExpectedCashRub: slot.ExpectedCashRub, SuggestedISIN: slot.SuggestedISIN,
		SuggestedName: slot.SuggestedName, ConfirmedISIN: slot.ConfirmedISIN,
		GapDays: slot.GapDays, SourcePositionISIN: slot.SourcePositionISIN,
		Status: status, FailureReason: failureReason, EligibleCandidates: candidates,
	}
}

func ValidateSlotReplacement(
	p Portfolio,
	universe []bonds.BondRecord,
	slot ReinvestmentSlot,
	confirmedISIN string,
) *string {
	universeByISIN := make(map[string]bonds.BondRecord)
	for _, b := range universe {
		universeByISIN[b.ISIN] = b
	}
	bond, ok := universeByISIN[confirmedISIN]
	if !ok {
		msg := fmt.Sprintf("облигация %s не найдена в универсе MOEX", confirmedISIN)
		return &msg
	}
	ctx := SelectionContext(p.RiskProfile, p.HorizonDate, slot.PurchaseDate(), p.APITradeOnly, &slot.ExpectedCashRub)
	if reason := BondEligibilityReason(bond, ctx, DefaultBondSelectionPolicy, true); reason != nil {
		return reason
	}
	if invalid := ValidateReplacementBond(bond, slot.PurchaseDate(), p.HorizonDate); invalid != nil {
		return invalid
	}
	if lotCost := bond.PricePerLotRub(); lotCost != nil && *lotCost > 0 && slot.ExpectedCashRub < *lotCost {
		msg := fmt.Sprintf("ожидаемого кэша (%.0f ₽) не хватает на 1 лот (%.0f ₽)", slot.ExpectedCashRub, *lotCost)
		return &msg
	}
	return nil
}

func PruneStaleSlotOverrides(p *Portfolio, resolved []ReinvestmentSlot) bool {
	active := make(map[string]struct{})
	for _, slot := range resolved {
		if slot.SourcePositionISIN != nil {
			active[*slot.SourcePositionISIN] = struct{}{}
		}
	}
	before := len(p.Slots)
	var kept []ReinvestmentSlot
	for _, slot := range p.Slots {
		if slot.SourcePositionISIN != nil {
			if _, ok := active[*slot.SourcePositionISIN]; ok {
				kept = append(kept, slot)
			}
		}
	}
	p.Slots = kept
	return len(p.Slots) != before
}

func ClearSlotOverride(p *Portfolio, sourceISIN *string) bool {
	if sourceISIN == nil {
		return false
	}
	changed := false
	var kept []ReinvestmentSlot
	for _, slot := range p.Slots {
		if slot.SourcePositionISIN != nil && *slot.SourcePositionISIN == *sourceISIN {
			if slot.ConfirmedISIN != nil {
				changed = true
			}
			if slot.ConfirmedISIN != nil || *slot.SourcePositionISIN != *sourceISIN {
				kept = append(kept, slot)
			}
			continue
		}
		kept = append(kept, slot)
	}
	if changed {
		p.Slots = kept
	}
	return changed
}

func SelectReplacement(
	universe []bonds.BondRecord,
	targetDate time.Time,
	profile RiskProfile,
	amount float64,
	horizonDate time.Time,
	keyRate, taxRate float64,
	apiTradeOnly bool,
	opts *SelectionOptions,
	dp DurationPolicy,
) (*bonds.BondRecord, string) {
	ctx := SelectionContext(profile, horizonDate, targetDate, apiTradeOnly, &amount)
	return SelectBestBond(universe, ctx, DefaultBondSelectionPolicy, keyRate, taxRate, dp, opts)
}
