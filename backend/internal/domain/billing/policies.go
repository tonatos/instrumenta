package billing

import "time"

// Policy holds billing timing knobs.
type Policy struct {
	PastDueGraceDays int
}

// DefaultPolicy returns production defaults.
func DefaultPolicy() Policy {
	return Policy{PastDueGraceDays: 3}
}

// PeriodDuration returns how long a paid period lasts.
func PeriodDuration(period Period) time.Duration {
	switch period {
	case PeriodYear:
		return 365 * 24 * time.Hour
	default:
		return 30 * 24 * time.Hour
	}
}

// ExtendPeriodEnd advances period end from the later of now or current end.
func ExtendPeriodEnd(currentEnd, now time.Time, period Period) time.Time {
	base := now
	if currentEnd.After(now) {
		base = currentEnd
	}
	return base.Add(PeriodDuration(period))
}

// YearlySavingsKopecks compares 12× monthly vs yearly price.
func YearlySavingsKopecks(monthKopecks, yearKopecks int64) int64 {
	full := monthKopecks * 12
	if full <= yearKopecks {
		return 0
	}
	return full - yearKopecks
}

// YearlySavingsPercent is (savings / 12×month) * 100.
func YearlySavingsPercent(monthKopecks, yearKopecks int64) float64 {
	full := monthKopecks * 12
	if full <= 0 {
		return 0
	}
	return float64(YearlySavingsKopecks(monthKopecks, yearKopecks)) / float64(full) * 100
}

// EffectiveMonthlyKopecks for display (year / 12 rounded).
func EffectiveMonthlyKopecks(period Period, amountKopecks int64) int64 {
	if period == PeriodYear {
		return amountKopecks / 12
	}
	return amountKopecks
}

