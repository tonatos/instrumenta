package portfolio

import "time"

type SimEventKind int

const (
	SimEventCoupon SimEventKind = iota
	SimEventMaturity
	SimEventPutOffer
	SimEventDeployCash
)

type SimEvent struct {
	Kind               SimEventKind
	Date               time.Time
	PositionID         *int64
	SourcePositionISIN *string
	TriggerReason      *ReinvestmentTriggerReason
	ConfirmedISIN      *string
	IsPut              bool
	ParentGeneration   int
}

type ScheduledEvent struct {
	SortKey [3]int
	Event   SimEvent
}

func simEventPriority(kind SimEventKind) int {
	switch kind {
	case SimEventCoupon:
		return 0
	case SimEventMaturity, SimEventPutOffer:
		return 1
	default:
		return 2
	}
}

func simSortKey(date time.Time, kind SimEventKind, seq int) [3]int {
	return [3]int{int(date.Unix()), simEventPriority(kind), seq}
}
