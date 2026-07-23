package billing

import "time"

// ApplySuccessfulPayment activates or extends a subscription after a verified payment.
// Grandfathering: renewals keep sub.AmountKopecks / Features; first payment / change_period
// adopt plan version amounts and features.
func ApplySuccessfulPayment(
	sub *Subscription,
	plan PlanVersion,
	ownerTelegramID int64,
	purpose string,
	now time.Time,
	paymentMethodID string,
) Subscription {
	if now.IsZero() {
		now = time.Now().UTC()
	}
	if sub == nil {
		features := append([]Feature(nil), plan.Features...)
		return Subscription{
			OwnerTelegramID:    ownerTelegramID,
			Status:             StatusActive,
			PlanVersionID:      plan.ID,
			Period:             plan.Period,
			AmountKopecks:      plan.AmountKopecks,
			Features:           features,
			CurrentPeriodStart: now,
			CurrentPeriodEnd:   now.Add(PeriodDuration(plan.Period)),
			CancelAtPeriodEnd:  false,
			PaymentMethodID:    paymentMethodID,
			PastDueSince:       nil,
			CreatedAt:          now,
			UpdatedAt:          now,
		}
	}

	out := *sub
	out.UpdatedAt = now
	out.Status = StatusActive
	out.PastDueSince = nil
	out.CancelAtPeriodEnd = false
	if paymentMethodID != "" {
		out.PaymentMethodID = paymentMethodID
	}

	switch purpose {
	case "change_period":
		out.PlanVersionID = plan.ID
		out.Period = plan.Period
		out.AmountKopecks = plan.AmountKopecks
		out.Features = append([]Feature(nil), plan.Features...)
		out.CurrentPeriodStart = now
		out.CurrentPeriodEnd = now.Add(PeriodDuration(plan.Period))
	case "renew":
		// Keep grandfathered amount/features/period; only extend end.
		out.CurrentPeriodEnd = ExtendPeriodEnd(out.CurrentPeriodEnd, now, out.Period)
		if out.CurrentPeriodStart.IsZero() {
			out.CurrentPeriodStart = now
		}
	default: // checkout (first or re-subscribe after expired)
		out.PlanVersionID = plan.ID
		out.Period = plan.Period
		out.AmountKopecks = plan.AmountKopecks
		out.Features = append([]Feature(nil), plan.Features...)
		out.CurrentPeriodStart = now
		out.CurrentPeriodEnd = now.Add(PeriodDuration(plan.Period))
	}
	return out
}

// MarkCancelAtPeriodEnd sets soft-cancel; access remains until CurrentPeriodEnd.
func MarkCancelAtPeriodEnd(sub Subscription, now time.Time) Subscription {
	sub.CancelAtPeriodEnd = true
	sub.UpdatedAt = now
	return sub
}

// MarkPastDue transitions after a failed renewal.
func MarkPastDue(sub Subscription, now time.Time) Subscription {
	sub.Status = StatusPastDue
	t := now
	sub.PastDueSince = &t
	sub.UpdatedAt = now
	return sub
}

// MarkExpired ends access after grace.
func MarkExpired(sub Subscription, now time.Time) Subscription {
	sub.Status = StatusExpired
	sub.UpdatedAt = now
	sub.CancelAtPeriodEnd = false
	return sub
}

// ShouldAttemptRenew is true when period ended, not canceling, and method exists.
func ShouldAttemptRenew(sub Subscription, now time.Time) bool {
	if sub.PaymentMethodID == "" {
		return false
	}
	if sub.CancelAtPeriodEnd {
		return false
	}
	switch sub.Status {
	case StatusActive:
		return !sub.CurrentPeriodEnd.After(now)
	case StatusPastDue:
		return true
	default:
		return false
	}
}

// ShouldExpirePastDue is true when grace elapsed.
func ShouldExpirePastDue(sub Subscription, now time.Time, policy Policy) bool {
	if sub.Status != StatusPastDue {
		return false
	}
	if policy.PastDueGraceDays == 0 {
		policy = DefaultPolicy()
	}
	deadline := sub.CurrentPeriodEnd.AddDate(0, 0, policy.PastDueGraceDays)
	if sub.PastDueSince != nil {
		fromPastDue := sub.PastDueSince.AddDate(0, 0, policy.PastDueGraceDays)
		if fromPastDue.Before(deadline) {
			deadline = fromPastDue
		}
	}
	return now.After(deadline)
}

// ShouldExpireCanceled ends access when canceled and period finished.
func ShouldExpireCanceled(sub Subscription, now time.Time) bool {
	if !sub.CancelAtPeriodEnd && sub.Status != StatusCanceled {
		return false
	}
	if sub.Status == StatusExpired {
		return false
	}
	return sub.CurrentPeriodEnd.Before(now) || sub.CurrentPeriodEnd.Equal(now)
}
