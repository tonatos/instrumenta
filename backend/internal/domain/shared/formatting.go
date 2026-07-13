package shared

import (
	"fmt"
	"strings"
	"time"
)

const MissingValue = "—"

var ruMonthsGenitive = []string{
	"",
	"января", "февраля", "марта", "апреля", "мая", "июня",
	"июля", "августа", "сентября", "октября", "ноября", "декабря",
}

// FormatDate renders a human-readable Russian date.
func FormatDate(value *time.Time, reference ...time.Time) string {
	if value == nil {
		return MissingValue
	}
	ref := DateOnly(time.Now())
	if len(reference) > 0 {
		ref = DateOnly(reference[0])
	}
	v := DateOnly(*value)
	month := ruMonthsGenitive[int(v.Month())]
	if v.Year() == ref.Year() {
		return fmt.Sprintf("%d %s", v.Day(), month)
	}
	return fmt.Sprintf("%d %s %d", v.Day(), month, v.Year())
}

// FormatNumber formats with non-breaking-space thousands separator.
func FormatNumber(value float64, decimals int) string {
	s := fmt.Sprintf("%.*f", decimals, value)
	parts := strings.Split(s, ".")
	intPart := parts[0]
	neg := false
	if strings.HasPrefix(intPart, "-") {
		neg = true
		intPart = intPart[1:]
	}
	var grouped []string
	for len(intPart) > 3 {
		grouped = append([]string{intPart[len(intPart)-3:]}, grouped...)
		intPart = intPart[:len(intPart)-3]
	}
	grouped = append([]string{intPart}, grouped...)
	out := strings.Join(grouped, "\u00a0")
	if len(parts) > 1 {
		out += "." + parts[1]
	}
	if neg {
		out = "-" + out
	}
	return out
}
