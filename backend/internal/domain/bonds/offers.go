package bonds

import (
	"fmt"
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

type OfferKind string

const OfferKindPut OfferKind = "put"

type OfferWindowStatus string

const (
	OfferWindowUnknown  OfferWindowStatus = "unknown"
	OfferWindowNotOpen  OfferWindowStatus = "not_open"
	OfferWindowOpen     OfferWindowStatus = "open"
	OfferWindowClosed   OfferWindowStatus = "closed"
	OfferWindowExpired  OfferWindowStatus = "expired"
)

type PutOfferDecision string

const (
	PutOfferPending  PutOfferDecision = "pending"
	PutOfferExercise PutOfferDecision = "exercise"
	PutOfferHold     PutOfferDecision = "hold"
)

type OfferSchedule interface {
	GetOfferDate() *time.Time
	GetOfferSubmissionStart() *time.Time
	GetOfferSubmissionEnd() *time.Time
	GetOfferPricePct() *float64
	GetCallDate() *time.Time
}

type BondOfferView struct {
	Kind            OfferKind
	ExecutionDate   time.Time
	SubmissionStart *time.Time
	SubmissionEnd   *time.Time
	PricePct        *float64
	WindowStatus    OfferWindowStatus
	MoexOfferType   *string
}

func OfferWindowStatusFor(
	offerDate, submissionStart, submissionEnd *time.Time,
	asOf time.Time,
) *OfferWindowStatus {
	if offerDate == nil {
		return nil
	}
	asOf = shared.DateOnly(asOf)
	od := shared.DateOnly(*offerDate)
	if !od.After(asOf) {
		s := OfferWindowExpired
		return &s
	}
	// Incomplete window (only start or only end) is not actionable — wait for both dates.
	if submissionStart == nil || submissionEnd == nil {
		s := OfferWindowUnknown
		return &s
	}
	if asOf.Before(shared.DateOnly(*submissionStart)) {
		s := OfferWindowNotOpen
		return &s
	}
	if asOf.After(shared.DateOnly(*submissionEnd)) {
		s := OfferWindowClosed
		return &s
	}
	s := OfferWindowOpen
	return &s
}

func BondOfferViewFrom(source OfferSchedule, asOf time.Time) *BondOfferView {
	offerDate := source.GetOfferDate()
	if offerDate == nil {
		return nil
	}
	status := OfferWindowStatusFor(
		offerDate,
		source.GetOfferSubmissionStart(),
		source.GetOfferSubmissionEnd(),
		asOf,
	)
	if status == nil {
		return nil
	}
	return &BondOfferView{
		Kind:            OfferKindPut,
		ExecutionDate:   shared.DateOnly(*offerDate),
		SubmissionStart: source.GetOfferSubmissionStart(),
		SubmissionEnd:   source.GetOfferSubmissionEnd(),
		PricePct:        source.GetOfferPricePct(),
		WindowStatus:    *status,
	}
}

func PutOfferAwarenessMessage(view BondOfferView) string {
	execution := shared.FormatDate(&view.ExecutionDate)
	switch view.WindowStatus {
	case OfferWindowUnknown:
		return fmt.Sprintf("Пут-оферта %s — окно подачи ещё не объявлено эмитентом", execution)
	case OfferWindowNotOpen:
		if view.SubmissionStart != nil {
			return fmt.Sprintf(
				"Пут-оферта %s — приём заявок с %s",
				execution,
				shared.FormatDate(view.SubmissionStart),
			)
		}
	case OfferWindowOpen:
		if view.SubmissionEnd != nil {
			return fmt.Sprintf(
				"Пут-оферта %s — подайте заявку до %s включительно",
				execution,
				shared.FormatDate(view.SubmissionEnd),
			)
		}
	}
	return fmt.Sprintf("Пут-оферта %s", execution)
}

func PutOfferActionMessage(view BondOfferView) string {
	if view.SubmissionEnd != nil {
		return fmt.Sprintf(
			"Подайте заявку на пут-оферту до %s включительно (исполнение %s)",
			shared.FormatDate(view.SubmissionEnd),
			shared.FormatDate(&view.ExecutionDate),
		)
	}
	return fmt.Sprintf(
		"Подайте заявку на пут-оферту (исполнение %s)",
		shared.FormatDate(&view.ExecutionDate),
	)
}

// OfferWindowData is put-offer schedule fields from an external source (MOEX / T-Invest).
type OfferWindowData struct {
	OfferDate       *time.Time
	SubmissionStart *time.Time
	SubmissionEnd   *time.Time
	PricePct        *float64
}

// SelectOfferWindow picks the offer matching preferDate, else the nearest future offer on/after asOf.
func SelectOfferWindow(offers []OfferWindowData, preferDate *time.Time, asOf time.Time) *OfferWindowData {
	if len(offers) == 0 {
		return nil
	}
	asOf = shared.DateOnly(asOf)
	if preferDate != nil {
		prefer := shared.DateOnly(*preferDate)
		for i := range offers {
			if offers[i].OfferDate == nil {
				continue
			}
			if shared.DateOnly(*offers[i].OfferDate).Equal(prefer) {
				return &offers[i]
			}
		}
	}
	var best *OfferWindowData
	for i := range offers {
		od := offers[i].OfferDate
		if od == nil {
			continue
		}
		d := shared.DateOnly(*od)
		if d.Before(asOf) {
			continue
		}
		if best == nil || d.Before(shared.DateOnly(*best.OfferDate)) {
			best = &offers[i]
		}
	}
	return best
}

// ApplyOfferWindow fills missing put-offer window fields. Does not overwrite set values.
// When bond.OfferDate and patch.OfferDate are both set, they must match.
func ApplyOfferWindow(bond *BondRecord, patch OfferWindowData) bool {
	if bond == nil {
		return false
	}
	if bond.OfferDate != nil && patch.OfferDate != nil {
		if !shared.DateOnly(*bond.OfferDate).Equal(shared.DateOnly(*patch.OfferDate)) {
			return false
		}
	}
	changed := false
	if bond.OfferDate == nil && patch.OfferDate != nil {
		d := shared.DateOnly(*patch.OfferDate)
		bond.OfferDate = &d
		changed = true
	}
	if bond.OfferSubmissionStart == nil && patch.SubmissionStart != nil {
		d := shared.DateOnly(*patch.SubmissionStart)
		bond.OfferSubmissionStart = &d
		changed = true
	}
	if bond.OfferSubmissionEnd == nil && patch.SubmissionEnd != nil {
		d := shared.DateOnly(*patch.SubmissionEnd)
		bond.OfferSubmissionEnd = &d
		changed = true
	}
	if bond.OfferPricePct == nil && patch.PricePct != nil {
		v := *patch.PricePct
		bond.OfferPricePct = &v
		changed = true
	}
	return changed
}
