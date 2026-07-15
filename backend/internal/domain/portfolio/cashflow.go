package portfolio

import (
	"sort"
	"strings"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

// CashflowEvent is an atomic cashflow line in the portfolio plan.
type CashflowEvent struct {
	Date         time.Time
	Kind         string
	AmountRub    float64
	Description  string
	RelatedISIN  *string
	IsProjected  bool
	PositionID   *int64
	Lots         *int
	BondsCount   *int
	JournalSeq   int
}

var causalKindOrder = map[string]int{"coupon": 0, "maturity": 1, "put_offer": 1, "purchase": 2}

func EventSortKey(e CashflowEvent) (time.Time, int) {
	order := map[string]int{"purchase": 0, "coupon": 1, "maturity": 2, "put_offer": 2}
	return e.Date, order[e.Kind]
}

func JournalSortKey(e CashflowEvent) (time.Time, int) {
	if e.JournalSeq > 0 {
		return e.Date, e.JournalSeq
	}
	return e.Date, causalKindOrder[e.Kind]
}

func sortedJournal(events []CashflowEvent) []CashflowEvent {
	out := append([]CashflowEvent(nil), events...)
	sort.Slice(out, func(i, j int) bool {
		di, oi := JournalSortKey(out[i])
		dj, oj := JournalSortKey(out[j])
		if di.Equal(dj) {
			return oi < oj
		}
		return di.Before(dj)
	})
	return out
}

// JoinCashflowJournals merges historical and projected journal segments in sort order.
func JoinCashflowJournals(segments ...[]CashflowEvent) []CashflowEvent {
	var combined []CashflowEvent
	for _, seg := range segments {
		combined = append(combined, seg...)
	}
	return sortedJournal(combined)
}

func RunningCashBeforePurchase(events []CashflowEvent, purchaseDate time.Time, initialCash float64) float64 {
	cash := initialCash
	for _, event := range sortedJournal(events) {
		if event.Date.After(purchaseDate) {
			break
		}
		if event.Date.Before(purchaseDate) {
			cash += event.AmountRub
			continue
		}
		if event.Kind == "purchase" {
			break
		}
		cash += event.AmountRub
	}
	return cash
}

func CashOnHandBeforeDate(events []CashflowEvent, asOf time.Time, initialCash float64) float64 {
	cash := initialCash
	for _, event := range sortedJournal(events) {
		if !event.Date.Before(asOf) {
			break
		}
		cash += event.AmountRub
	}
	return cash
}

type CashflowRow struct {
	Date            string
	AmountRub       float64
	Kind            string
	Label           string
	Lots            *int
	BondsCount      *int
	BalanceAfterRub float64
}

func CashflowRowsWithBalance(events []CashflowEvent, initialCash float64) []CashflowRow {
	return CashflowRowsFromDate(events, initialCash, time.Time{})
}

// CashflowProjectedRowsFromToday returns forward-looking plan rows (projected events from as-of date).
func CashflowProjectedRowsFromToday(events []CashflowEvent, initialCash float64, today time.Time) []CashflowRow {
	today = shared.DateOnly(today)
	if today.IsZero() {
		return CashflowRowsWithBalance(events, initialCash)
	}
	running := CashOnHandBeforeDate(events, today, initialCash)
	var rows []CashflowRow
	for _, event := range sortedJournal(events) {
		if event.Date.Before(today) || !event.IsProjected {
			continue
		}
		running += event.AmountRub
		rows = append(rows, CashflowRow{
			Date:            shared.FormatISODate(event.Date),
			AmountRub:       event.AmountRub,
			Kind:            event.Kind,
			Label:           event.Description,
			Lots:            event.Lots,
			BondsCount:      event.BondsCount,
			BalanceAfterRub: round2(running),
		})
	}
	return rows
}

// CashflowRowsFromDate builds display rows from fromDate inclusive; balance starts at cash on that date.
func CashflowRowsFromDate(events []CashflowEvent, initialCash float64, fromDate time.Time) []CashflowRow {
	running := initialCash
	if !fromDate.IsZero() {
		running = CashOnHandBeforeDate(events, fromDate, initialCash)
	}
	var rows []CashflowRow
	for _, event := range sortedJournal(events) {
		if !fromDate.IsZero() && event.Date.Before(fromDate) {
			continue
		}
		running += event.AmountRub
		rows = append(rows, CashflowRow{
			Date:            shared.FormatISODate(event.Date),
			AmountRub:       event.AmountRub,
			Kind:            event.Kind,
			Label:           event.Description,
			Lots:            event.Lots,
			BondsCount:      event.BondsCount,
			BalanceAfterRub: round2(running),
		})
	}
	return rows
}

func round2(v float64) float64 {
	return float64(int(v*100+0.5)) / 100
}

func CashflowEventDescription(kind, name string, bondsCount, lots *int, priceSuffix string) string {
	suffix := formatBondsCountSuffix(bondsCount)
	switch kind {
	case "purchase":
		l := 0
		if lots != nil {
			l = *lots
		}
		return "Покупка " + itoa(l) + " лот(а) — " + name + suffix
	case "coupon":
		return "Купон по " + name + suffix
	case "put_offer":
		return "Пут-оферта по " + name + priceSuffix + suffix
	default:
		return "Погашение " + name + suffix
	}
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	n := v
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}

func formatBondsCountSuffix(bondsCount *int) string {
	if bondsCount == nil || *bondsCount <= 0 {
		return ""
	}
	return " (" + itoa(*bondsCount) + " шт.)"
}

func bondNameFromDescription(description string) string {
	text := description
	if strings.HasSuffix(text, " шт.)") {
		text = strings.Split(text, " (")[0]
	}
	if idx := strings.Index(text, " — "); idx >= 0 {
		return text[idx+3:]
	}
	for _, prefix := range []string{"Купон по ", "Погашение ", "Пут-оферта по "} {
		if strings.HasPrefix(text, prefix) {
			return text[len(prefix):]
		}
	}
	return text
}

var mergeableKinds = map[string]bool{"coupon": true, "maturity": true, "put_offer": true, "purchase": true}

func refreshMergedDescription(e *CashflowEvent) {
	if e.RelatedISIN == nil {
		return
	}
	name := bondNameFromDescription(e.Description)
	if e.Kind == "purchase" {
		e.Description = CashflowEventDescription("purchase", name, e.BondsCount, e.Lots, "")
		return
	}
	priceSuffix := ""
	if e.Kind == "put_offer" && strings.Contains(e.Description, " (") {
		tail := strings.SplitN(e.Description, " (", 2)[1]
		if strings.Contains(tail, "% номинала)") {
			priceSuffix = " (" + strings.Split(tail, ")")[0] + ")"
		}
	}
	e.Description = CashflowEventDescription(e.Kind, name, e.BondsCount, nil, priceSuffix)
}

type mergeKey struct {
	date time.Time
	kind string
	isin string
}

func MergeCashflowEvents(events []CashflowEvent) []CashflowEvent {
	sorted := sortedJournal(events)
	merged := make(map[mergeKey]*CashflowEvent)
	var order []mergeKey
	var passthrough []CashflowEvent
	for _, event := range sorted {
		if !mergeableKinds[event.Kind] || event.RelatedISIN == nil {
			passthrough = append(passthrough, event)
			continue
		}
		key := mergeKey{event.Date, event.Kind, *event.RelatedISIN}
		existing, ok := merged[key]
		if !ok {
			copy := event
			merged[key] = &copy
			order = append(order, key)
			continue
		}
		existing.AmountRub += event.AmountRub
		existing.IsProjected = existing.IsProjected || event.IsProjected
		if event.JournalSeq > 0 && (existing.JournalSeq == 0 || event.JournalSeq < existing.JournalSeq) {
			existing.JournalSeq = event.JournalSeq
		}
		if event.Lots != nil {
			v := derefInt(existing.Lots) + *event.Lots
			existing.Lots = &v
		}
		if event.BondsCount != nil {
			v := derefInt(existing.BondsCount) + *event.BondsCount
			existing.BondsCount = &v
		}
		refreshMergedDescription(existing)
	}
	var result []CashflowEvent
	for _, key := range order {
		result = append(result, *merged[key])
	}
	result = append(result, passthrough...)
	return sortedJournal(result)
}

func derefInt(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

func slotSortKey(slot ReinvestmentSlot) (time.Time, int, string) {
	reasonOrder := map[ReinvestmentTriggerReason]int{
		TriggerMaturity: 0, TriggerPutOffer: 1, TriggerCouponCash: 2,
	}
	src := ""
	if slot.SourcePositionISIN != nil {
		src = *slot.SourcePositionISIN
	} else if eff := slot.EffectiveISIN(); eff != nil {
		src = *eff
	}
	return slot.TriggerDate, reasonOrder[slot.TriggerReason], src
}

func copySlot(slot ReinvestmentSlot) ReinvestmentSlot {
	return ReinvestmentSlot{
		TriggerDate: slot.TriggerDate, TriggerReason: slot.TriggerReason,
		ExpectedCashRub: slot.ExpectedCashRub, SuggestedISIN: slot.SuggestedISIN,
		SuggestedName: slot.SuggestedName, ConfirmedISIN: slot.ConfirmedISIN,
		GapDays: slot.GapDays, SourcePositionISIN: slot.SourcePositionISIN,
	}
}

func accumulateSlot(existing, slot *ReinvestmentSlot) {
	existing.ExpectedCashRub += slot.ExpectedCashRub
	if existing.ConfirmedISIN == nil {
		existing.ConfirmedISIN = slot.ConfirmedISIN
	}
	if existing.SuggestedISIN == nil {
		existing.SuggestedISIN = slot.SuggestedISIN
	}
	if existing.SuggestedName == nil {
		existing.SuggestedName = slot.SuggestedName
	}
	priority := map[ReinvestmentTriggerReason]int{TriggerMaturity: 0, TriggerPutOffer: 1, TriggerCouponCash: 2}
	if priority[slot.TriggerReason] < priority[existing.TriggerReason] {
		existing.TriggerReason = slot.TriggerReason
		existing.TriggerDate = slot.TriggerDate
		if slot.SourcePositionISIN != nil {
			existing.SourcePositionISIN = slot.SourcePositionISIN
		}
	} else {
		if slot.TriggerDate.Before(existing.TriggerDate) {
			existing.TriggerDate = slot.TriggerDate
		}
		if existing.SourcePositionISIN == nil {
			existing.SourcePositionISIN = slot.SourcePositionISIN
		}
	}
}

func mergeSlotGroups(slots []ReinvestmentSlot, keyFn func(ReinvestmentSlot) string) []ReinvestmentSlot {
	sorted := append([]ReinvestmentSlot(nil), slots...)
	sort.Slice(sorted, func(i, j int) bool {
		di, oi, si := slotSortKey(sorted[i])
		dj, oj, sj := slotSortKey(sorted[j])
		if di.Equal(dj) {
			if oi == oj {
				return si < sj
			}
			return oi < oj
		}
		return di.Before(dj)
	})
	merged := make(map[string]*ReinvestmentSlot)
	var order []string
	var passthrough []ReinvestmentSlot
	for _, slot := range sorted {
		key := keyFn(slot)
		if key == "" {
			passthrough = append(passthrough, slot)
			continue
		}
		if existing, ok := merged[key]; ok {
			accumulateSlot(existing, &slot)
			continue
		}
		copy := copySlot(slot)
		merged[key] = &copy
		order = append(order, key)
	}
	var result []ReinvestmentSlot
	for _, key := range order {
		result = append(result, *merged[key])
	}
	result = append(result, passthrough...)
	sort.Slice(result, func(i, j int) bool {
		di, oi, si := slotSortKey(result[i])
		dj, oj, sj := slotSortKey(result[j])
		if di.Equal(dj) {
			if oi == oj {
				return si < sj
			}
			return oi < oj
		}
		return di.Before(dj)
	})
	return result
}

func slotMergeKey(slot ReinvestmentSlot) string {
	if slot.TriggerReason == TriggerCouponCash {
		return slot.TriggerDate.Format("2006-01-02") + "|" + string(slot.TriggerReason)
	}
	if slot.SourcePositionISIN != nil {
		return slot.TriggerDate.Format("2006-01-02") + "|" + string(slot.TriggerReason) + "|" + *slot.SourcePositionISIN
	}
	return ""
}

func slotCoalesceKey(slot ReinvestmentSlot) string {
	eff := slot.EffectiveISIN()
	if eff == nil {
		return ""
	}
	return slot.PurchaseDate().Format("2006-01-02") + "|" + *eff
}

func MergeReinvestmentSlots(slots []ReinvestmentSlot) []ReinvestmentSlot {
	bySource := mergeSlotGroups(slots, slotMergeKey)
	return mergeSlotGroups(bySource, slotCoalesceKey)
}
