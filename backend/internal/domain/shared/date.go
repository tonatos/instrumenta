package shared

import "time"

// DateOnly truncates t to UTC midnight.
func DateOnly(t time.Time) time.Time {
	y, m, d := t.Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

// MustParseDate parses YYYY-MM-DD or panics.
func MustParseDate(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return DateOnly(t)
}

// FormatISODate returns YYYY-MM-DD.
func FormatISODate(t time.Time) string {
	return DateOnly(t).Format("2006-01-02")
}

// AddDays returns date + n calendar days.
func AddDays(t time.Time, days int) time.Time {
	return DateOnly(t).AddDate(0, 0, days)
}

// DaysBetween returns whole calendar days from a to b (b - a).
func DaysBetween(a, b time.Time) int {
	a = DateOnly(a)
	b = DateOnly(b)
	return int(b.Sub(a).Hours() / 24)
}
