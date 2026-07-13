package portfolio

import (
	"time"

	"github.com/tonatos/bond-monitor/backend/internal/domain/bonds"
	"github.com/tonatos/bond-monitor/backend/internal/domain/shared"
)

const PutOfferReminderDays = 30

func putOfferWindowStatus(position PortfolioPosition, asOf time.Time) *bonds.OfferWindowStatus {
	return bonds.OfferWindowStatusFor(
		position.OfferDate,
		position.OfferSubmissionStart,
		position.OfferSubmissionEnd,
		asOf,
	)
}

// PutOfferBuyBlocked returns a rejection reason when put-offer window blocks purchase.
func PutOfferBuyBlocked(b bonds.BondRecord, asOf time.Time) *string {
	status := bonds.OfferWindowStatusFor(
		b.OfferDate, b.OfferSubmissionStart, b.OfferSubmissionEnd, asOf,
	)
	if status == nil || *status != bonds.OfferWindowClosed {
		return nil
	}
	if b.OfferSubmissionEnd == nil || b.OfferDate == nil {
		return nil
	}
	msg := "окно подачи по пут-оферте закрыто " + shared.FormatDate(b.OfferSubmissionEnd) +
		", оферта " + shared.FormatDate(b.OfferDate) + " — предъявить уже нельзя"
	return &msg
}

func PutOfferSubmissionClosed(position PortfolioPosition, asOf time.Time) bool {
	status := putOfferWindowStatus(position, asOf)
	if status == nil {
		return true
	}
	return *status == bonds.OfferWindowClosed || *status == bonds.OfferWindowExpired
}

func PutOfferCanExercise(position PortfolioPosition, asOf time.Time) bool {
	status := putOfferWindowStatus(position, asOf)
	return status != nil && *status == bonds.OfferWindowOpen
}

func PutOfferAwarenessDue(position PortfolioPosition, today time.Time) bool {
	view := bonds.BondOfferViewFrom(position, today)
	if view == nil {
		return false
	}
	if view.WindowStatus != bonds.OfferWindowUnknown && view.WindowStatus != bonds.OfferWindowNotOpen {
		return false
	}
	return shared.DaysBetween(today, view.ExecutionDate) <= PutOfferReminderDays
}

func PutOfferSubmitDue(position PortfolioPosition, today time.Time) bool {
	if position.PutOfferDecision != bonds.PutOfferPending {
		return false
	}
	if !PutOfferCanExercise(position, today) {
		return false
	}
	view := bonds.BondOfferViewFrom(position, today)
	if view == nil {
		return false
	}
	if view.SubmissionEnd != nil {
		days := shared.DaysBetween(today, *view.SubmissionEnd)
		return days >= 0 && days <= PutOfferReminderDays
	}
	return shared.DaysBetween(today, view.ExecutionDate) <= PutOfferReminderDays
}

func PositionPlansPutExit(position PortfolioPosition, today time.Time, assumeBestPutOutcome bool) bool {
	if position.OfferDate == nil || !position.OfferDate.After(today) {
		return false
	}
	if PutOfferSubmissionClosed(position, today) {
		return false
	}
	offerPrice := 100.0
	if position.OfferPricePct != nil {
		offerPrice = *position.OfferPricePct
	}
	if offerPrice < 100 {
		return false
	}
	switch position.PutOfferDecision {
	case bonds.PutOfferExercise:
		return true
	case bonds.PutOfferHold:
		return false
	default:
		return assumeBestPutOutcome
	}
}
