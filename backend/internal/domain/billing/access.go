package billing

import "time"

// AccessInput is everything needed to decide feature access (pure).
type AccessInput struct {
	Complimentary bool
	Subscription  *Subscription
	Now           time.Time
	Policy        Policy
}

// HasAccess reports whether the owner may use feature.
func HasAccess(in AccessInput, feature Feature) bool {
	if in.Complimentary {
		return true
	}
	if in.Subscription == nil {
		return false
	}
	sub := in.Subscription
	if !HasFeature(sub.Features, feature) {
		return false
	}
	now := in.Now
	if now.IsZero() {
		now = time.Now().UTC()
	}
	policy := in.Policy
	if policy.PastDueGraceDays == 0 {
		policy = DefaultPolicy()
	}

	switch sub.Status {
	case StatusActive:
		if sub.CurrentPeriodEnd.Before(now) {
			return false
		}
		return true
	case StatusPastDue:
		// Grace: still entitled until grace window after period end (or PastDueSince).
		deadline := sub.CurrentPeriodEnd.AddDate(0, 0, policy.PastDueGraceDays)
		if sub.PastDueSince != nil {
			graceFrom := sub.PastDueSince.AddDate(0, 0, policy.PastDueGraceDays)
			if graceFrom.Before(deadline) {
				deadline = graceFrom
			}
		}
		return !now.After(deadline)
	case StatusCanceled:
		// Canceled but still inside paid period.
		return !sub.CurrentPeriodEnd.Before(now)
	default: // expired
		return false
	}
}

// EntitledFeatures returns features the owner currently has.
func EntitledFeatures(in AccessInput) []Feature {
	if in.Complimentary {
		return PaidFeaturesV1()
	}
	if in.Subscription == nil {
		return nil
	}
	var out []Feature
	for _, f := range in.Subscription.Features {
		if HasAccess(in, f) {
			out = append(out, f)
		}
	}
	return out
}

// IsEntitled is a convenience wrapper.
func IsEntitled(complimentary bool, sub *Subscription, feature Feature, now time.Time) bool {
	return HasAccess(AccessInput{
		Complimentary: complimentary,
		Subscription:  sub,
		Now:           now,
		Policy:        DefaultPolicy(),
	}, feature)
}
