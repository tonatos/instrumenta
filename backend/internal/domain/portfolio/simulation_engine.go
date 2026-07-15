package portfolio

import (
	"container/heap"
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

type SimulationResult struct {
	Events            []CashflowEvent
	AllPositions      []PortfolioPosition
	ResolvedSlots     []ReinvestmentSlot
	HeldPositions     []HeldPositionAtHorizon
	UpcomingPutOffers []UpcomingPutOffer
	Notes             []string
	InitialCashRub    float64
}

type eventHeap []ScheduledEvent

func (h eventHeap) Len() int { return len(h) }
func (h eventHeap) Less(i, j int) bool {
	a, b := h[i].SortKey, h[j].SortKey
	for k := 0; k < 3; k++ {
		if a[k] != b[k] {
			return a[k] < b[k]
		}
	}
	return false
}
func (h eventHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *eventHeap) Push(x any)   { *h = append(*h, x.(ScheduledEvent)) }
func (h *eventHeap) Pop() any {
	old := *h
	n := len(old)
	item := old[n-1]
	*h = old[:n-1]
	return item
}

var phantomSources = map[PositionSourceType]bool{
	PositionSourceReinvestMaturity: true,
	PositionSourceReinvestPutOffer: true,
	PositionSourceReinvestCoupon:   true,
}

func generationFor(position PortfolioPosition) int {
	if phantomSources[position.Source] {
		return 1
	}
	return 0
}

func reinvestSourceType(isPut bool) PositionSourceType {
	if isPut {
		return PositionSourceReinvestPutOffer
	}
	return PositionSourceReinvestMaturity
}

func simPositionIsPutAtEnd(position PortfolioPosition, endDate *time.Time, today time.Time) bool {
	return endDate != nil && position.OfferDate != nil &&
		endDate.Equal(*position.OfferDate) &&
		!PutOfferSubmissionClosed(position, today)
}

func scheduleLifecycle(
	h *eventHeap,
	entry *OpenPosition,
	horizon, today time.Time,
	assumeBestPutOutcome bool,
	seq *int,
) {
	if entry.Closed {
		return
	}
	position := entry.Position
	positionID := position.ID
	endDate := PositionEndDate(position, horizon, today, assumeBestPutOutcome)
	couponEnd := horizon
	if endDate != nil && !endDate.After(horizon) {
		couponEnd = *endDate
	}
	couponGross := CouponPaymentPerEvent(position)
	if couponGross > 0 {
		for _, couponDate := range CouponDatesInRange(position, couponEnd) {
			*seq++
			pid := positionID
			heap.Push(h, ScheduledEvent{
				SortKey: simSortKey(couponDate, SimEventCoupon, *seq),
				Event: SimEvent{Kind: SimEventCoupon, Date: couponDate, PositionID: &pid},
			})
		}
	}
	if endDate == nil || endDate.After(horizon) {
		return
	}
	isPut := simPositionIsPutAtEnd(position, endDate, today)
	kind := SimEventMaturity
	if isPut {
		kind = SimEventPutOffer
	}
	reason := TriggerMaturity
	if isPut {
		r := TriggerPutOffer
		reason = r
	}
	*seq++
	src := position.ISIN
	pid := positionID
	heap.Push(h, ScheduledEvent{
		SortKey: simSortKey(*endDate, kind, *seq),
		Event: SimEvent{
			Kind: kind, Date: *endDate, PositionID: &pid,
			SourcePositionISIN: &src, TriggerReason: &reason, IsPut: isPut,
		},
	})
}

func scheduleDeploy(
	h *eventHeap,
	deployDate time.Time,
	sourceISIN string,
	reason ReinvestmentTriggerReason,
	confirmedISIN *string,
	isPut bool,
	parentGeneration int,
	seq *int,
	scheduled map[string]struct{},
) {
	key := deployDate.Format("2006-01-02")
	if _, ok := scheduled[key]; ok {
		return
	}
	scheduled[key] = struct{}{}
	*seq++
	heap.Push(h, ScheduledEvent{
		SortKey: simSortKey(deployDate, SimEventDeployCash, *seq),
		Event: SimEvent{
			Kind: SimEventDeployCash, Date: deployDate,
			SourcePositionISIN: &sourceISIN, TriggerReason: &reason,
			ConfirmedISIN: confirmedISIN, IsPut: isPut, ParentGeneration: parentGeneration,
		},
	})
}

func findEntry(state *PortfolioState, positionID int64) *OpenPosition {
	for i := range state.OpenPositions {
		if state.OpenPositions[i].Position.ID == positionID {
			return &state.OpenPositions[i]
		}
	}
	return nil
}

func appendJournal(result *SimulationResult, journalSeq *int, event CashflowEvent) {
	*journalSeq++
	event.JournalSeq = *journalSeq
	result.Events = append(result.Events, event)
}

func appendHeld(
	result *SimulationResult,
	position PortfolioPosition,
	universeByISIN map[string]bonds.BondRecord,
) {
	liveBond, ok := universeByISIN[position.ISIN]
	var estValue float64
	source := "номинал × кол-во (нет рыночной цены)"
	if ok {
		if dirty := liveBond.DirtyPriceRub(); dirty != nil && *dirty > 0 {
			estValue = *dirty * float64(position.BondsCount())
			source = "live MOEX (грязная цена × кол-во)"
		} else {
			estValue = position.FaceValue * float64(position.BondsCount())
		}
	} else {
		estValue = position.FaceValue * float64(position.BondsCount())
	}
	result.HeldPositions = append(result.HeldPositions, HeldPositionAtHorizon{
		Position: position, EstimatedValueRub: estValue, ValuationSource: source,
	})
}

func maybePutReminder(
	result *SimulationResult,
	position PortfolioPosition,
	universeByISIN map[string]bonds.BondRecord,
	today, horizon time.Time,
	reminded map[string]struct{},
) {
	if position.OfferDate == nil {
		return
	}
	if today.After(*position.OfferDate) || position.OfferDate.After(horizon) {
		return
	}
	if _, ok := reminded[position.ISIN]; ok {
		return
	}
	if liveBond, ok := universeByISIN[position.ISIN]; ok {
		SyncPutOfferFromBond(&position, liveBond)
	}
	daysUntil := shared.DaysBetween(today, *position.OfferDate)
	var daysUntilSubEnd *int
	if position.OfferSubmissionEnd != nil {
		v := shared.DaysBetween(today, *position.OfferSubmissionEnd)
		daysUntilSubEnd = &v
	}
	canExercise := PutOfferCanExercise(position, today) && !PutOfferSubmissionClosed(position, today)
	if !PutOfferSubmitDue(position, today) && !PutOfferAwarenessDue(position, today) {
		return
	}
	result.UpcomingPutOffers = append(result.UpcomingPutOffers, UpcomingPutOffer{
		Position: position, DaysUntil: daysUntil, DaysUntilSubmissionEnd: daysUntilSubEnd,
		SubmissionStart: position.OfferSubmissionStart, SubmissionEnd: position.OfferSubmissionEnd,
		OfferPricePct: position.OfferPricePct, CanExercise: canExercise,
	})
	reminded[position.ISIN] = struct{}{}
}

// RunSimulation builds the cashflow journal via event-sourced simulation.
func RunSimulation(
	p Portfolio,
	universe []bonds.BondRecord,
	today, horizon time.Time,
	keyRate, taxRate, initialCash float64,
	planCtx PlanContext,
	durationPolicy DurationPolicy,
) SimulationResult {
	universeByISIN := make(map[string]bonds.BondRecord)
	for _, b := range universe {
		universeByISIN[b.ISIN] = b
	}
	result := SimulationResult{InitialCashRub: initialCash}
	state := NewPortfolioState(initialCash)

	savedSlots := make(map[string]ReinvestmentSlot)
	for _, slot := range p.Slots {
		if slot.SourcePositionISIN != nil {
			savedSlots[*slot.SourcePositionISIN] = slot
		}
	}

	seedPositions := OpenPositions(p.Positions)
	for i := range seedPositions {
		if bond, ok := universeByISIN[seedPositions[i].ISIN]; ok {
			SyncPutOfferFromBond(&seedPositions[i], bond)
		}
	}

	var queue eventHeap
	seq, journalSeq := 0, 0
	scheduledDeploy := make(map[string]struct{})
	reminded := make(map[string]struct{})
	isTrading := planCtx.IsTrading()
	assumeBestPutOutcome := planCtx.AssumeBestPutOutcome

	for _, position := range seedPositions {
		gen := generationFor(position)
		entry := state.AddPosition(position, gen)
		emitPurchase := !isTrading && position.Source == PositionSourceInitial && !position.PurchaseDate.After(today)
		if emitPurchase {
			lots, bondsCount := position.Lots, position.BondsCount()
			isin := position.ISIN
			pid := position.ID
			appendJournal(&result, &journalSeq, CashflowEvent{
				Date: position.PurchaseDate, Kind: "purchase", AmountRub: -position.PurchaseAmountRub,
				Description: CashflowEventDescription("purchase", position.Name, &bondsCount, &lots, ""),
				RelatedISIN: &isin, IsProjected: position.PurchaseDate.After(today),
				PositionID: &pid, Lots: &lots, BondsCount: &bondsCount,
			})
			state.Cash -= position.PurchaseAmountRub
		}
		endDate := PositionEndDate(position, horizon, today, assumeBestPutOutcome)
		if endDate == nil || endDate.After(horizon) {
			appendHeld(&result, position, universeByISIN)
		} else {
			scheduleLifecycle(&queue, entry, horizon, today, assumeBestPutOutcome, &seq)
		}
		maybePutReminder(&result, position, universeByISIN, today, horizon, reminded)
	}

	heap.Init(&queue)
	for queue.Len() > 0 {
		scheduled := heap.Pop(&queue).(ScheduledEvent)
		event := scheduled.Event
		if event.Date.After(horizon) {
			continue
		}
		if isTrading && event.Date.Before(today) {
			continue
		}

		switch event.Kind {
		case SimEventCoupon:
			if event.PositionID == nil || !state.IsOpen(*event.PositionID) {
				continue
			}
			entry := findEntry(state, *event.PositionID)
			if entry == nil {
				continue
			}
			position := entry.Position
			netFactor := 1 - taxRate
			gross := CouponPaymentPerEvent(position)
			if gross <= 0 {
				continue
			}
			bondsCount := position.BondsCount()
			isin := position.ISIN
			pid := position.ID
			appendJournal(&result, &journalSeq, CashflowEvent{
				Date: event.Date, Kind: "coupon", AmountRub: gross * netFactor,
				Description: CashflowEventDescription("coupon", position.Name, &bondsCount, nil, ""),
				RelatedISIN: &isin, IsProjected: event.Date.After(today), PositionID: &pid, BondsCount: &bondsCount,
			})
			state.Cash += gross * netFactor

		case SimEventMaturity, SimEventPutOffer:
			if event.PositionID == nil || !state.IsOpen(*event.PositionID) {
				continue
			}
			entry := findEntry(state, *event.PositionID)
			if entry == nil {
				continue
			}
			position := entry.Position
			isPut := event.Kind == SimEventPutOffer
			kind := "maturity"
			priceSuffix := ""
			if isPut {
				kind = "put_offer"
				if position.OfferPricePct != nil {
					priceSuffix = fmt.Sprintf(" (%.0f%% номинала)", *position.OfferPricePct)
				}
			}
			redemption := NetRedemptionAmount(position, taxRate, isPut)
			bondsCount := position.BondsCount()
			isin := position.ISIN
			pid := position.ID
			appendJournal(&result, &journalSeq, CashflowEvent{
				Date: event.Date, Kind: kind, AmountRub: redemption,
				Description: CashflowEventDescription(kind, position.Name, &bondsCount, nil, priceSuffix),
				RelatedISIN: &isin, IsProjected: event.Date.After(today), PositionID: &pid, BondsCount: &bondsCount,
			})
			state.Cash += redemption
			state.ClosePosition(*event.PositionID)

			deployDate := shared.AddDays(event.Date, ReinvestmentGapDays)
			if deployDate.After(horizon) {
				continue
			}
			if entry.Generation >= MaxReinvestDepth {
				result.Notes = append(result.Notes, fmt.Sprintf(
					"%s: достигнут предел глубины реинвестиций (%d); дальнейшие цепочки не моделировались.",
					position.Name, MaxReinvestDepth,
				))
				continue
			}
			reason := TriggerMaturity
			if event.TriggerReason != nil {
				reason = *event.TriggerReason
			}
			var slot ReinvestmentSlot
			if saved, ok := savedSlots[position.ISIN]; ok {
				slot = ReinvestmentSlot{
					TriggerDate: event.Date, TriggerReason: reason, ExpectedCashRub: 0,
					SuggestedISIN: saved.SuggestedISIN, SuggestedName: saved.SuggestedName,
					ConfirmedISIN: saved.ConfirmedISIN, GapDays: ReinvestmentGapDays,
					SourcePositionISIN: &position.ISIN,
				}
			} else {
				slot = ReinvestmentSlot{
					TriggerDate: event.Date, TriggerReason: reason, ExpectedCashRub: 0,
					GapDays: ReinvestmentGapDays, SourcePositionISIN: &position.ISIN,
				}
			}
			result.ResolvedSlots = append(result.ResolvedSlots, slot)
			scheduleDeploy(&queue, deployDate, position.ISIN, reason, slot.ConfirmedISIN, isPut, entry.Generation, &seq, scheduledDeploy)

		case SimEventDeployCash:
			cashAtDeploy := state.Cash
			if cashAtDeploy <= 0 {
				continue
			}
			source := reinvestSourceType(event.IsPut)
			confirmed := event.ConfirmedISIN
			if confirmed != nil {
				if bond, ok := universeByISIN[*confirmed]; ok {
					if invalid := ValidateReplacementBond(bond, event.Date, horizon); invalid != nil && event.SourcePositionISIN != nil {
						ClearSlotOverride(&p, event.SourcePositionISIN)
						result.Notes = append(result.Notes, fmt.Sprintf(
							"Слот %s: override «%s» отклонён (%s).",
							shared.FormatDate(&event.Date), *confirmed, *invalid,
						))
						confirmed = nil
					}
				}
			}
			allocations, remaining, deployNotes := DeployCash(
				cashAtDeploy, state.LotsByISIN(), universe, p.RiskProfile, horizon, event.Date,
				keyRate, taxRate, p.APITradeOnly, p.AccountKind, durationPolicy, confirmed, source,
			)
			detail := "замена не подобрана"
			if len(deployNotes) > 0 {
				detail = deployNotes[len(deployNotes)-1]
			}
			if len(allocations) > 0 {
				primary := allocations[0]
				for i := range allocations {
					if allocations[i].EstimatedAmountRub > primary.EstimatedAmountRub {
						primary = allocations[i]
					}
				}
				for i := range result.ResolvedSlots {
					s := &result.ResolvedSlots[i]
					if event.SourcePositionISIN != nil && s.SourcePositionISIN != nil &&
						*s.SourcePositionISIN == *event.SourcePositionISIN &&
						s.PurchaseDate().Equal(event.Date) {
						s.SuggestedISIN = &primary.ISIN
						s.SuggestedName = &primary.Name
					}
				}
			} else {
				sourceName := "позиция"
				if event.SourcePositionISIN != nil {
					sourceName = *event.SourcePositionISIN
				}
				for _, pos := range state.AllPositions {
					if event.SourcePositionISIN != nil && pos.ISIN == *event.SourcePositionISIN {
						sourceName = pos.Name
						break
					}
				}
				result.Notes = append(result.Notes, fmt.Sprintf(
					"%s: на дату %s не нашлось подходящей замены — %s. Деньги останутся в кэш-балансе.",
					sourceName, shared.FormatDate(&event.Date), detail,
				))
			}
			if len(deployNotes) > 0 && len(allocations) > 0 {
				result.Notes = append(result.Notes, "Реинвест "+shared.FormatDate(&event.Date)+": "+deployNotes[len(deployNotes)-1])
			}
			for _, allocation := range allocations {
				bond, ok := universeByISIN[allocation.ISIN]
				if !ok || !HasUsablePrice(bond) {
					continue
				}
				if state.Cash <= 0.01 {
					break
				}
				phantom := PositionFromBond(bond, allocation.Lots, event.Date, source)
				cost := phantom.PurchaseAmountRub
				if cost > state.Cash+0.01 {
					lotPrice := 0.0
					if p := bond.PricePerLotRub(); p != nil {
						lotPrice = *p
					}
					if lotPrice <= 0 {
						continue
					}
					affordable := int(state.Cash / lotPrice)
					if affordable < 1 {
						continue
					}
					phantom = PositionFromBond(bond, affordable, event.Date, source)
					cost = phantom.PurchaseAmountRub
				}
				if cost > state.Cash+0.01 {
					continue
				}
				gen := event.ParentGeneration + 1
				entry := state.AddPosition(phantom, gen)
				state.Cash -= cost
				lots, bondsCount := phantom.Lots, phantom.BondsCount()
				isin := phantom.ISIN
				pid := phantom.ID
				appendJournal(&result, &journalSeq, CashflowEvent{
					Date: event.Date, Kind: "purchase", AmountRub: -cost,
					Description: CashflowEventDescription("purchase", phantom.Name, &bondsCount, &lots, ""),
					RelatedISIN: &isin, IsProjected: event.Date.After(today), PositionID: &pid, Lots: &lots, BondsCount: &bondsCount,
				})
				endDate := PositionEndDate(phantom, horizon, today, assumeBestPutOutcome)
				if endDate == nil || endDate.After(horizon) {
					appendHeld(&result, phantom, universeByISIN)
				} else if gen <= MaxReinvestDepth {
					scheduleLifecycle(&queue, entry, horizon, today, assumeBestPutOutcome, &seq)
				}
			}
			if remaining > 0 && len(allocations) == 0 {
				result.Notes = append(result.Notes, fmt.Sprintf(
					"%s: кэш %.0f ₽ не распределён.", shared.FormatDate(&event.Date), cashAtDeploy,
				))
			}
		}
	}

	result.AllPositions = append([]PortfolioPosition(nil), state.AllPositions...)
	return result
}
